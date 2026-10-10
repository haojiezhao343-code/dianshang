import json
import uuid
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from api.routers.dependencies import get_dialogue_service
from api.schemas import ChatRequest, ChatResponse, ChatBotMessage, ChatObject,HistoryMessage,HistoryResponse
from conf.config import settings
from domain.messages import ProcessResult, UserMessage, MessageType, FocusedObject
from service.dialogue_service import DialogueService

router = APIRouter()


# 定义路由接口

@router.post("/api/chat")
async def chat_endpoint(
        chat_request: ChatRequest,
        dialogue_service: DialogueService = Depends(get_dialogue_service)
) -> ChatResponse:
    # 1. 处理输入接口模型
    user_message = _build_user_message(chat_request)
    # 2. 业务处理
    process_result: ProcessResult = await dialogue_service.process_message(user_message)
    # 3. 处理输出接口模型
    return _build_chat_response(process_result)

@router.get("/api/digital-human/credentials")
async def get_digital_human_credentials():
    """前端获取数字人（魔珐星云）SDK 初始化凭证。
    密钥仅存储在后端 .env，不暴露在前端源码中。
    """
    return {
        "app_id": settings.digital_human_app_id,
        "app_secret": settings.digital_human_app_secret,
        "gateway_server": settings.digital_human_gateway_server,
    }

@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    dialogue_service: DialogueService = Depends(get_dialogue_service),
):
    await websocket.accept()
    print(f"[WebSocket] 新客户端已连接")

    try:
        # 2. 持续接收客户端消息
        while True:
            # 接收原始文本
            raw_data = await websocket.receive_text()

            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "data": {"code": "INVALID_JSON", "message": "消息格式错误，需要 JSON"}
                })
                continue

            msg_type = payload.get("type")
            if msg_type == "cancel":
                sender_id = payload.get("sender_id")
                # TODO: 通知 dialogue_service 取消该用户的正在生成任务
                await websocket.send_json({
                    "type": "status",
                    "sender_id": sender_id,
                    "data": {"status": "cancelled"}
                })
                continue

                # --------------------------------------------------
                # 处理 "message" 类型：正常聊天消息
                # --------------------------------------------------
            if msg_type == "message":
                sender_id = payload.get("sender_id")
                text = payload.get("text")
                message_id = payload.get("message_id") or uuid.uuid4().hex
                obj_payload = payload.get("object")

                # ① 构建 UserMessage（与 HTTP 接口逻辑一致）
                user_message = UserMessage(
                    sender_id=sender_id,
                    message_id=message_id,
                    type=MessageType.TEXT if text else MessageType.OBJECT,
                    text=text if text else None,
                    object=FocusedObject(
                        id=obj_payload["id"],
                        type=obj_payload["type"],
                        title=obj_payload.get("title"),
                        attributes=obj_payload.get("attributes") or {},
                    ) if obj_payload else None
                )

                # ② 发送"正在思考"状态
                await websocket.send_json({
                    "type": "status",
                    "sender_id": sender_id,
                    "data": {"status": "thinking"}
                })

                try:
                    # ③ 调用对话服务（与 POST /api/chat 一致）
                    process_result: ProcessResult = await dialogue_service.process_message(user_message)

                    # ④ 流式逐条返回 Bot 消息
                    for bot_msg in process_result.messages:
                        await websocket.send_json({
                            "type": "bot_message",
                            "sender_id": process_result.sender_id,
                            "message_id": process_result.message_id,
                            "data": {
                                "text": bot_msg.text,
                                "object": {
                                    "type": bot_msg.object.type,
                                    "id": bot_msg.object.id,
                                    "title": bot_msg.object.title,
                                    "attributes": bot_msg.object.attributes
                                } if bot_msg.object else None
                            }
                        })

                    # ⑤ 发送"完成"状态
                    await websocket.send_json({
                        "type": "status",
                        "sender_id": sender_id,
                        "data": {"status": "done"}
                    })

                except Exception as e:
                    # ⑥ 处理异常
                    await websocket.send_json({
                        "type": "error",
                        "sender_id": sender_id,
                        "data": {
                            "code": "PROCESS_ERROR",
                            "message": str(e)
                        }
                    })

    except WebSocketDisconnect:
        # 客户端主动断开连接
        print(f"[WebSocket] 客户端已断开连接")
    except Exception as e:
        # 其他异常，尝试发送错误信息后关闭
        print(f"[WebSocket] 发生异常: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"code": "INTERNAL_ERROR", "message": "服务器内部错误"}
            })
        except Exception:
            pass
        await websocket.close()


def _build_user_message(chat_request: ChatRequest) -> UserMessage:
    """
    将请求数据模型转换为领域数据模型 供业务使用
    :param chat_request:
    :return:
    """
    return UserMessage(
        sender_id=chat_request.sender_id,
        message_id=chat_request.message_id if chat_request.message_id else str(uuid.uuid4()),
        type=MessageType.TEXT if chat_request.text else MessageType.OBJECT,
        text=chat_request.text,
        object=FocusedObject(
            id=chat_request.object.id,
            type=chat_request.object.type,
            title=chat_request.object.title,
            attributes=chat_request.object.attributes,
        ) if chat_request.object else None
    )


def _build_chat_response(process_result: ProcessResult) -> ChatResponse:
    return ChatResponse(
        sender_id=process_result.sender_id,
        message_id=process_result.message_id,
        messages=[
            ChatBotMessage(
                text=bot_msg.text,
                object=ChatObject(
                    type=bot_msg.object.type,
                    id=bot_msg.object.id,
                    title=bot_msg.object.title,
                    attributes=bot_msg.object.attributes
                ) if bot_msg.object else None
            )
            for bot_msg in process_result.messages
        ]
    )

@router.get('/api/chat/history')
async def history(sender_id: str) -> HistoryResponse:
    return HistoryResponse(
        sender_id=sender_id,
        messages=[
            HistoryMessage(role='user', text='你好'),
            HistoryMessage(role='bot', text='我不好'),
        ],
    )