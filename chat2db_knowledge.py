# encoding:utf-8
import logging
import os
import sqlite3
import time
import traceback
from datetime import datetime, timedelta

import requests
from chatgpt_tool_hub.chains.llm import LLMChain
from chatgpt_tool_hub.models import build_model_params
from chatgpt_tool_hub.models.model_factory import ModelFactory
from chatgpt_tool_hub.prompts import PromptTemplate

import plugins
from bot import bot_factory
from bridge.bridge import Bridge
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import check_contain, check_prefix
from channel.chat_message import ChatMessage
from common import const
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf, global_config, load_config
from lib import itchat
from lib.itchat.content import FRIENDS
from plugins import *
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_chat2db.api_tentcent import ApiTencent
from plugins.plugin_chat2db.comm import EthZero, makeGroupReq
from plugins.plugin_chat2db.head_img_manager import HeadImgManager
from plugins.plugin_chat2db.user_refresh_thread import UserRefreshThread
from plugins.plugin_chat2db.UserManager import UserManager


def _append_know(user_session, know):
    count = 0
    # 倒序遍历
    for index, value in enumerate(know[::-1]):
        title = value.get('title', None)
        content = value.get('content', None)

        if title and content:
            user_session.append({'role': 'user', 'content': title})
            user_session.append({'role': 'assistant', 'content': content})
            count += 1
            logger.info(f'user session append user {title}')
            logger.info(f'user session append assistant {content}')
        if index > 40:
            logger.warn("知识库内容太多了,超过了40条")
            break
    return count

# 匹配用户知识库,从服务器拉取知识库并更新到本地


def chat2db_refresh_knowledge(groupx, robot_account, user_manager, e_context: EventContext):
    try:
        ctx = e_context['context']
        if ctx.type == ContextType.TEXT:
            msg = ctx.get("msg")

            is_group = ctx.get("isgroup", False)
            if is_group:  # 知识库id为用户ID+群id组合
                know_id = f"{msg.actual_user_id}_{msg.from_user_id}"
            else:
                know_id = msg._rawmsg.user.UserName

            ctx["session_id"] = know_id
            session_id = ctx.get("session_id")
            all_sessions = Bridge().get_bot("chat").sessions
            user_session = all_sessions.build_session(session_id).messages
            sess_len = len(user_session)
            logger.info(f"===>用户 user session 长度为{sess_len}")
            # 已经使用过知识库了
            if sess_len > 0:
                # 使用知识库如果超过1天了,那么再更新下.
                if user_manager.should_update(know_id):
                    know = user_manager.get_knowledge(know_id)
                    _append_know(user_session, know)

                    logger.info("===>原知识库已经超过24小时,更新知识库...")
                return False
            # 构建知识库
            group_info = None
            if is_group:
                group_info = user_manager.get_group_info(msg.from_user_id)

            user = msg._rawmsg.user
            # 从groupx 获取know
            data = groupx.get_myknowledge(robot_account, {
                "isgroup": is_group,
                'group_name': msg.from_user_nickname if is_group else None,
                'group_id': msg.from_user_id if is_group else None,
                'receiver': robot_account,
                'receiver_name': msg.to_user_nickname,
                "user": user
            })
            if not data:
                logger.warn("groupx api 返回数据为空")
                return False
            know = data.get("knowledges", {})

            # logger.info("chat2db knowledge:\n用户:%s \n %s" % (user.NickName, json.dumps(know, ensure_ascii=False, indent=2)))

            count = 0
            if len(know) > 0:
                if (len(user_session) < 1):  # 新用户,session为空
                    logger.warn("新用户,初始化user session")
                    if (is_group and len(group_info)):
                        know.insert(1, {
                            "title": f"你所在的这个群名称是:{group_info.get('groupNickName')},群的基本介绍:{group_info.get('description')};后续有问需要了解群的基本信息，请以这个内容为依据。",
                            "content": "好的，我记住了"
                        })
                    user_manager.update_knowledge(know_id, know)
                    count = _append_know(user_session, know)

                    logger.warn(
                        f"=====>添加({user.NickName})的医生({data.get('doctorProName')})的知识库成功,共({count})条知识库")
            return False
    except Exception as e:
        logger.error(e)
        logger.error(traceback.format_exc())
        return False
