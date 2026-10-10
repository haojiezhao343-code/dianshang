# itwwy/api/dependencies.py

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from service.dialogue_service import DialogueService
from repository.dialogue_state_repository import DialogueStateRepository
from engine.dialogue_engine import DialogueEngine
from infrastructure import database
from plan.turn_planner import TurnPlanner
from task.action.builder import build_action_runner
from task.flow.executor import FlowExecutor
from task.flow.loader import FlowLoader
from pathlib import Path
from task.handler import TaskHandler
from task.command.processor import CommandProcessor
from clarify.responder import ClarifyResponder
from plan.turn_validator import TurnPlanValidator
from task.action.runner import ActionRunner

# 拿数据库连接 操作层连接

async def get_session():
    async with database.async_session() as session:  # 异步方式获取session  获取session要网络传输（耗时的）
        yield session


async def get_dialogue_state_repository(session: AsyncSession = Depends(get_session)):
    return DialogueStateRepository(session=session)

# 获取会话引擎
async def get_engine():
    base = Path(__file__).resolve().parents[2]
    flow_list = FlowLoader().load_many([
        base / "flow_config" / "user_flows.yml",
        base / "flow_config" / "system_flows.yml",
    ]) # 读yml 文件

    # 调用了会话引擎
    return DialogueEngine(
        turn_planner=TurnPlanner(),# 执行计划
        task_handler=TaskHandler(flows=flow_list, command_processor=CommandProcessor(),action_runner=build_action_runner(),flow_executor=FlowExecutor()),# 任务处理
        clarify_responder=ClarifyResponder(),# 澄清影响
        turn_plan_validator=TurnPlanValidator(), # 校验器
    )


async def get_dialogue_service(
        dialogue_state_repository: DialogueStateRepository = Depends(get_dialogue_state_repository),
        dialogue_engine: DialogueEngine = Depends(get_engine)
) -> DialogueService:
    return DialogueService(dialogue_state_repository=dialogue_state_repository, dialogue_engine=dialogue_engine)
