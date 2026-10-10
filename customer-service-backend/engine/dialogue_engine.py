# itwwy/engine/dialogue_engine.py

import logging
import time

from domain.state import DialogueState
from domain.messages import UserMessage, ProcessResult, BotMessage, MessageType
from plan.models import ClarifyReason
from task.command.models import Command, SetSlotsCommand
from task.flow.flows import FlowsList
from task.flow.steps import CollectFlowStep
from plan.turn_planner import TurnPlanner
from plan.turn_validator import TurnPlanValidator
from task.handler import TaskHandler
from clarify.responder import ClarifyResponder

logger = logging.getLogger(__name__)


class DialogueEngine:

    def __init__(
            self,
            turn_planner: TurnPlanner,
            task_handler: TaskHandler,
            # knowledge_handler: KnowledgeHandler,
            # chitchat_handler: ChitchatHandler,
            clarify_responder: ClarifyResponder,
            turn_plan_validator: TurnPlanValidator
    ) -> None:
        pass
        self.turn_planner = turn_planner
        self.task_handler = task_handler
        # self.knowledge_handler = knowledge_handler
        # self.chitchat_handler = chitchat_handler
        self.clarify_responder = clarify_responder
        self.turn_plan_validator = turn_plan_validator

    def _prepare_session(self, dialogue_state: DialogueState) -> None:
        """
        准备会话
        :param dialogue_state:
        :return:
        """
        # 1. 获取当前会话
        session = dialogue_state.current_session()
        # 2. 如果当前会话不存在，则创建一个会话
        if session is None:
            dialogue_state.start_session()
            return
        # 3. 判断会话是否超时
        now = time.time()
        if now - session.last_activity_at > 60 * 60:  # 1小时
            # 关闭会话
            dialogue_state.close_current_session()
            # 重置运行时状态
            dialogue_state.reset_runtime_state_for_new_session()
            # 创建会话
            dialogue_state.start_session()
        else:  #
            # 更新会话（会话续期）  会话 创建 活跃时间 关闭时间
            session.last_activity_at = now

    def _begin_turn(self, dialogue_state: DialogueState, user_message: UserMessage) -> None:
        """
        开始一个turn
        :param dialogue_state:
        :param user_message:
        :return:
        """
        dialogue_state.begin_turn(user_message)

    # ── 最小修复：收集槽位确定性兜底 + 各轨道兜底话术 ──────────────────
    # 正在等待用户补槽（系统流程 system_collect_information）时，
    # 若 LLM 未把用户输入识别为 set_slots，则直接把这句话当作槽值填入，
    # 避免流程原地反复重问模板句（如"请简单说一下退款原因。"）。
    _FALLBACK_CHITCHAT = "你好，我是电商小二智能客服～我可以帮你查订单、查物流、申请退款，或者解答商品和售后问题。"
    _FALLBACK_KNOWLEDGE = "这个问题我先记下啦～目前你可以直接问我：订单状态、物流进度、商品详情，或者说\"我要退款\"来办理售后。"
    _FALLBACK_LLM_ERROR = "抱歉，我这边服务暂时有点不稳定，请稍后再试～你也可以直接说：查订单、查物流、我要退款。"

    def _pending_collect_slot(self, state: DialogueState) -> str | None:
        """当前系统流程是否正在等待补槽，是则返回槽位名。"""
        system_task = state.active_system_task
        if system_task is not None and getattr(system_task, "flow_id", None) == "system_collect_information":
            slot_name = getattr(system_task, "slot_name", "") or ""
            if slot_name:
                return slot_name
        return None

    @staticmethod
    def _commands_fill_slot(commands: list[Command], slot_name: str) -> bool:
        for cmd in commands:
            if isinstance(cmd, SetSlotsCommand) and slot_name in (cmd.slots or {}):
                return True
        return False

    @staticmethod
    def _commands_leave_flow(commands: list[Command]) -> bool:
        """用户明确要取消/切换流程时，不要用兜底填槽打断它。"""
        for cmd in commands:
            if type(cmd).__name__ in ("CancelFlowCommand", "ResumeFlowCommand", "StartFlowCommand"):
                return True
        return False

    async def _handle_text_message(self, dialogue_state: DialogueState) -> list[BotMessage]:

        user_text = (dialogue_state.pending_turn.user_message.text or "").strip()
        pending_slot = self._pending_collect_slot(dialogue_state)

        def fallback_fill_command() -> SetSlotsCommand | None:
            if pending_slot and user_text:
                return SetSlotsCommand(command="set_slots", slots={pending_slot: user_text})
            return None

        # 1. 调 LLM 生成本轮计划（确定任务轨道） 让LLM 决定 走哪条路
        try:
            turn_plan = await self.turn_planner.predict(dialogue_state, self.task_handler.flows)
        except Exception:
            logger.exception("TurnPlanner LLM 调用失败，走兜底逻辑")
            fill_cmd = fallback_fill_command()
            if fill_cmd is not None:
                return await self.task_handler.handle(commands=[fill_cmd], state=dialogue_state)
            return [BotMessage(text=self._FALLBACK_LLM_ERROR)]

        # 2. 防幻觉校验(本节不实现,后面讲)
        # TODO

        # 3. 按轨道分发
        if turn_plan.task is not None:
            commands = list(turn_plan.task.commands)
            # 确定性兜底：在补槽等待中，但 LLM 没给该槽赋值且用户不是要离开流程
            fill_cmd = fallback_fill_command()
            if (fill_cmd is not None
                    and not self._commands_fill_slot(commands, pending_slot)
                    and not self._commands_leave_flow(commands)):
                commands.append(fill_cmd)
            result = await self.task_handler.handle(commands=commands, state=dialogue_state)
            if not result and fill_cmd is not None:
                result = [BotMessage(text="好的，已收到～")]
            return result
        elif turn_plan.knowledge is not None:
            # 知识轨道未实现：补槽等待中先填槽推进流程，否则给引导话术
            fill_cmd = fallback_fill_command()
            if fill_cmd is not None:
                return await self.task_handler.handle(commands=[fill_cmd], state=dialogue_state)
            return [BotMessage(text=self._FALLBACK_KNOWLEDGE)]
        else:
            # 闲聊轨道未实现：同上
            fill_cmd = fallback_fill_command()
            if fill_cmd is not None:
                return await self.task_handler.handle(commands=[fill_cmd], state=dialogue_state)
            return [BotMessage(text=self._FALLBACK_CHITCHAT)]
    # ── 最小修复结束 ──────────────────────────────────────────────────

    @staticmethod
    def _flow_has_unfilled_collect_slot(
            state: DialogueState,
            flows: FlowsList,
            slot_name: str,
    ) -> bool:
        # 判断 什么 可以返回  不可以返回  指令
        """检查当前流程是否定义了名为 slot_name 的收集槽且尚未填充。"""
        active_task = state.active_task  # 如果当前没有活跃的流程  不会填槽 （）
        # 校验  当前没有正在进行的流程
        if active_task is None:  # ① 没有活跃流程
            return False

        # 当前有活跃的流程  refund_request退款流程  tuikuan_request
        flow = flows.get_flow_by_id(active_task.flow_id)
        if flow is None:  # ② 流程 id 查不到(防御)
            return False

        # 订单号  我已经  提取过了 不再提取
        if active_task.slots.get(slot_name):  # ③ 这个槽已经填了
            return False

        for step in flow.steps:  # ④ 流程里有没有收集这个槽的步骤
            if isinstance(step, CollectFlowStep) and step.slot_name == slot_name:
                return True

        return False

    def _resolve_object_commands(
            self,
            message: UserMessage,
            state: DialogueState,
            flows: FlowsList,
    ) -> list[Command]:
        # 当前聚焦的对象
        message_object = message.object
        if message_object is None:  # 鲁棒性校验
            return []

        # order product
        object_type = message_object.type.strip().lower()

        if object_type == "order":  # 订单
            if self._flow_has_unfilled_collect_slot(state, flows, "order_number"):
                """
                {
                    'commands': 'set_slot',
                     slots= {'order_number': '01001'}
                }
                """  # true
                return [SetSlotsCommand(
                    command="set_slots",
                    slots={"order_number": message_object.id},
                )]
            return []

        if object_type == "product":  # 商品
            if self._flow_has_unfilled_collect_slot(state, flows, "product_id"):
                # true
                """
                  {
                    'commands': 'set_slot',
                     slots= {'product_id': '01001'}
                }

                """
                return [SetSlotsCommand(
                    command="set_slots",
                    slots={"product_id": message_object.id},
                )]
            return []

        return []

    async def _handle_object_message(
            self,
            message: UserMessage,
            state: DialogueState,
    ) -> list[BotMessage]:
        # 将对象解析成command(SetSlotsCommand)
        commands = self._resolve_object_commands(
            message=message,
            state=state,
            flows=self.task_handler.flows,
        )

        if commands:
            # 场景 A:对象能填当前槽 → 转成命令,推进流程
            return await self.task_handler.handle(commands=commands, state=state)

        # 没有匹配到 slot。如果用户正在一个流程中,不打断,让流程继续。
        if state.active_task is not None:
            # 场景 C:在流程里但槽不匹配 → 不打断,空命令让流程继续
            return await self.task_handler.handle(commands=[], state=state)

        # 场景 B:没有流程 → 澄清

        return await self.clarify_responder.respond(
            state=state,
            reason=ClarifyReason.OBJECT_REQUIRES_INTENT,
        )

    async def process_message(self, dialogue_state: DialogueState,
                              user_message: UserMessage) -> ProcessResult:
        # TODO (用户的消息---->LLM路由(三条轨道的某一条) 执行某一条)
        # TODO  便利贴  TODOList  待办事项清单

        # 1. 准备会话
        self._prepare_session(dialogue_state)

        # 2. 开启本轮turn
        self._begin_turn(dialogue_state, user_message)

        # 3. 按消息类型分流
        if user_message.type is MessageType.TEXT:
            messages = await self._handle_text_message(dialogue_state)
        else:
            # 对象消息(本节不实现,后面讲)
            # 先将当前这一次 用户点击聚焦对象 存进状态  记录一下 当前聚焦的 是谁？
            dialogue_state.set_focused_object(user_message.object)

            # 调方法 要去处理 用户这一次 聚焦对象
            messages = await self._handle_object_message(message=user_message, state=dialogue_state)

        # 4. 把本轮回复写入turn
        dialogue_state.pending_turn.bot_messages.extend(messages)
        # 提交:turn 进入 session 历史（方法名以 domain/state.py 的 commit_turn 为准）
        dialogue_state.commit_turn()

        # 5. 组装返回结果
        return ProcessResult(
            sender_id=user_message.sender_id,
            message_id=user_message.message_id,
            messages=messages,
        )

        # return ProcessResult(
        #     sender_id=user_message.sender_id,
        #     message_id=user_message.message_id,
        #     messages=[
        #         BotMessage(text="我是智能小客服"),
        #         BotMessage(text="欢迎你来到这里...")
        #     ]
        #
        # )
