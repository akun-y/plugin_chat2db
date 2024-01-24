# encoding:utf-8

import json
import threading
import time
from hashlib import md5
from types import MemberDescriptorType
from typing import List

import arrow
import requests

import config as RobotConfig
from common.log import logger
from lib import itchat
from lib.itchat.content import *
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_chat2db.api_tencent import ApiTencent
from plugins.plugin_comm.plugin_comm import (
    EthZero,
    get_itchat_group,
    is_eth_address,
    make_chat_sign_req,
)
from plugins.plugin_chat2db.head_img_manager import HeadImgManager
from plugins.plugin_comm.remark_name_info import (
    RemarkNameInfo,
    set_chatroom_remark_name,
)

try:
    from channel.wechatnt.ntchat_channel import wechatnt
except Exception as e:
    print(f"未安装ntchat: {e}")


# 定时检测用户联系人及群组信息,同步最新的 wechat UserName


class UserRefreshThread(object):
    def __init__(self, conn, config):
        super().__init__()
        # 保存定时任务回调
        self._config = config
        self._conn = conn

        self.groupxHostUrl = self._config.get("groupx_host_url")
        self.groupx = ApiGroupx(self.groupxHostUrl)
        self.tencent = ApiTencent(self.groupxHostUrl)
        self.img_service = HeadImgManager(conn, self.groupxHostUrl)

        self.robot_account = config.get("account")
        self.robot_user_id = ""
        self.robot_user_nickname = ""  # config.get("name")
        self.check_login_second_interval = config.get(
            "check_login_second_interval", 60 * 100
        )  # 默认100分钟

        self.is_relogin = False

        self.postFriendsPos = 0
        self.postGroupsPos = 0

        self.friends = []
        self.chatrooms = []
        # 创建子线程
        t = threading.Thread(target=self.timer_sub_thread)
        t.setDaemon(True)
        t.start()

    # 定义子线程函数
    def timer_sub_thread(self):
        # 延迟15秒后再检测，让初始化任务执行完
        time.sleep(15)
        # 检测是否重新登录了
        self.is_relogin = False

        while True:
            # 定时检测
            self.timer_check()
            # 群组列表有没有增减
            chatrooms = itchat.get_chatrooms(True, True)
            if len(chatrooms) != len(self.chatrooms):
                self.chatrooms = chatrooms
                self.update_friends_groups()

            # time.sleep(int(100*60)) # 100*60秒(100分钟)检测一次
            time.sleep(int(self.check_login_second_interval))

    # 定时检查,检测机器人是否重新登录了(服务器重启时变化)
    def timer_check(self):
        # 检测是否重新登录了
        self.check_is_relogin()
        # 重新登录、未登录，均跳过
        if self.is_relogin:
            logger.warn(f"=====》服务器已重新登录,Bot UserName 更新为 {self.robot_user_id}")
            return
        logger.info(f"定时检测,bot UserName无变化 {self.robot_user_id}")

    # 检测是否重新登录了

    def check_is_relogin(self):
        # 机器人ID
        self.robot_user_id = ""
        # 通道
        channel_name = RobotConfig.conf().get("channel_type", "wx")
        if channel_name == "wx":
            self.robot_user_id = itchat.instance.storageClass.userName
            self.robot_user_nickname = itchat.instance.storageClass.nickName
        elif channel_name == "ntchat":
            try:
                login_info = wechatnt.get_login_info()
                nickname = login_info["nickname"]
                user_id = login_info["wxid"]
                self.robot_user_id = user_id
                self.robot_user_nickname = nickname
            except Exception as e:
                print(f"获取 ntchat的 userid 失败: {e}")
                # nt
                self.is_relogin = False
                return
        else:
            # 其他通道，默认不更新用户ID
            self.is_relogin = False
            return

        # 登录后
        if self.robot_user_id is not None and len(self.robot_user_id) > 0:
            # NTChat的userID不变
            if channel_name == "ntchat":
                self.is_relogin = False
                return

            # temp_isRelogin =True #调试时才用

            # 取出好友中的机器人用户,
            myself = self._get_friend(
                self.robot_user_nickname, self.robot_user_nickname
            )
            if myself is None:
                myselfUserName = ""
            else:
                myselfUserName = myself[0]
                logger.info(f"从本地表中读取bot的UserName:\n{myself[0]}\n{myself[3]}")
            #     model : TimeTaskModel = self.timeTasks[0]
            temp_isRelogin = self.robot_user_id != myselfUserName

            if temp_isRelogin:
                # 更新为重新登录态
                self.is_relogin = True
                # 等待登录完成
                time.sleep(30)

                # 更新userId
                self.update_friends_groups()

                # 更新为非重新登录态
                self.is_relogin = False
        else:
            # 置为重新登录态
            self.is_relogin = True

    def update_friends_groups(self):
        logger.info("更新用户ID,Friends, Groups")
        try:
            if self.postFriends2Groupx():
                self.saveFriends2DB()
            if self.postGroups2Groupx():
                self.saveGroups2DB()
        except Exception as e:
            logger.error(f"====>更新用户ID,Friends, Groups 失败: {e}")

    def saveFriends2DB(self):
        # 好友处理
        try:
            # 获取好友列表
            if len(self.friends) < 1:
                self.friends = itchat.get_friends(update=True)

            c = self._conn.cursor()
            logger.debug(
                "[saveFriends2DB] insert record: {} 条".format(len(self.friends))
            )
            for friend in self.friends:
                c.execute(
                    "INSERT OR REPLACE INTO friends_records VALUES (?,?,?,?,?,?)",
                    (
                        self.robot_user_id,
                        self.robot_user_nickname,
                        "",
                        friend.UserName,
                        friend.NickName,
                        friend.HeadImgUrl,
                    ),
                )

            self._conn.commit()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")

    def postFriends2Groupx(self):
        step = 50
        # 获取好友列表,每次100条,越界后又从0开始
        if len(self.friends) < 1:
            self.friends = itchat.get_friends(update=True)

        end = self.postFriendsPos + step
        if end > len(self.friends):
            end = len(self.friends) - 1
            
        friends = self.friends[self.postFriendsPos : end]
        logger.info(
            f"post friends to server :{self.postFriendsPos}->{end},本次:{len(friends)}个,总共:{len(self.friends)}"
        )

        self.postFriendsPos += step
        if len(friends) < step:
            # 全部好友都发送完成了
            self.postFriendsPos = 0
            logger.info(f"好友列表发送完成,共{len(self.friends)}个好友")
        else:
            # 每隔8秒执行一次,直到好友列表全部发送完成
            threading.Timer(8.0, self.postFriends2Groupx).start()

        ret = self.groupx.post_friends(
            self.robot_account, self.robot_user_nickname, friends
        )
        if ret is False:
            logger.error(f"post friends to groupx failed ${ret}")
            return False
        else:
            logger.info(f"post friends to groupx success 用户数:{len(ret)}")

        # filtered_data = [item for item in ret if item.get('account')]
        # logger.info(f"post friends have account :{len(filtered_data)}")
        # # 遍历字典的所有子项，为每个子项设置account字段
        # for friend in filtered_data:
        #     friendUserName = friend.get('UserName')
        #     # _usr = itchat.update_friend(friend.get('friendUserName'))
        #     _usr = itchat.search_friends(userName=friendUserName)
        #     if (_usr is None):
        #         _usr = itchat.update_friend(friendUserName)

        #     account = _usr.get('RemarkName', None)
        #     # ethAddr存在到RemarkName 中
        #     retAccount = friend.get('account', None)
        #     if (retAccount and account != retAccount):
        #         # 更新account到 RemarkName中
        #         logger.info(
        #             f'更新好友 {_usr.get("NickName")} account 为 {retAccount}')
        #         _usr.set_alias(retAccount)
        #         _usr.update()
        #         itchat.dump_login_status()

        return ret

    def saveGroups2DB(self):
        # 群组
        try:
            # 群聊 （id组装 旧
            if len(self.chatrooms) < 1:
                self.chatrooms = itchat.get_chatrooms()

            c = self._conn.cursor()
            logger.debug(
                "[saveGroups2DB] insert record: {} 条".format(len(self.chatrooms))
            )
            for chatroom in self.chatrooms:
                c.execute(
                    "INSERT OR REPLACE INTO groups_records VALUES (?,?,?,?,?,?,?,?)",
                    (
                        chatroom.get("UserName"),
                        chatroom.get("NickName"),
                        chatroom.get("DisplayName"),
                        chatroom.get("UserName"),
                        chatroom.get("NickName"),
                        chatroom.get("HeadImgUrl"),
                        chatroom.get("PYQuanPin"),
                        chatroom.get("EncryChatRoomId"),
                    ),
                )
            self._conn.commit()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            logger.error("群聊列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
        except Exception as err:
            logger.error(f"发生意外错误: {err}")

    def _merge_dict(self, dict1, dict2):
        for key, value in dict2.items():
            if key in dict1 and (
                not dict1[key]
                or (
                    isinstance(dict1[key], (list, tuple, str, dict))
                    and len(dict1[key]) < 1
                )
            ):
                # 如果 dict1 中的值是空字符串或者 None，使用 dict2 中的值覆盖
                dict1[key] = value
            elif key not in dict1:
                # 如果键在 dict1 中不存在，直接添加键值对
                dict1[key] = value
        return dict1

    # 根据服务器返回的group信息,更新RemarkName
    def _set_remark_name_chatrooms(self, groups_from_srv):
        for group in groups_from_srv:
            group_id = group.get("groupUserName") or group.get("UserName")
            set_chatroom_remark_name(group_id, group.get("objectId"))

    def _refresh_group_info(self, chatroom2):
        v = chatroom2
        # ----------------------------------------------
        # 设置RemarkName,通过search_friends,update_friend方法获取群信息时，会包括RemarkName
        if len(v["RemarkName"]) < 1:
            room1 = get_itchat_group(v["UserName"])
            if len(room1["RemarkName"]) > 0:
                v["RemarkName"] = room1["RemarkName"]
                logger.info(f"更新群 {v['NickName']} remarkName 为 {v['RemarkName']}")
        # ----------------------------------------------
        # 设置 memberList
        memberList = v["MemberList"]
        if len(memberList) < 1:
            room2 = itchat.update_chatroom(v["UserName"], True)
            if len(room2["MemberList"]) > 0:
                v["MemberList"] = room2["MemberList"]
                logger.info(
                    f"更新群 {v['NickName']} memberList 长度为 {len(v['MemberList'])}"
                )
        # ----------------------------------------------
        # 头像更新,放在最后,否则会被覆盖
        if v["HeadImgUrl"] is None or not v["HeadImgUrl"].startswith("http"):
            url = self.img_service.get_head_img_url(v.get("UserName"), True)
            if url and url.startswith("http"):
                v["HeadImgUrl"] = url
        # ----------------------------------------------
        logger.info(
            f"群:{v['NickName']} RM:{v['RemarkName']} 成员:({len(v['MemberList'])})个,头像:{v['HeadImgUrl'][0:10]}"
        )
        return v

    def postGroups2Groupx(self):
        step = 2
        # 获取群列表,每次30条,越界后又从0开始
        if len(self.chatrooms) < 1:
            self.chatrooms = itchat.get_chatrooms(True, False)

        chatrooms = self.chatrooms[self.postGroupsPos : self.postGroupsPos + step]
        self.postGroupsPos += step
        if len(chatrooms) < step:
            self.postGroupsPos = 0
            logger.info(f"群列表已发送完成,共:{len(self.chatrooms)}")
        else:
            # 每隔20秒执行一次,直到群列表全部发送完成
            threading.Timer(30.0, self.postGroups2Groupx).start()

        for index, value in enumerate(chatrooms):
            try:
                last_group = self._refresh_group_info(value)
                chatrooms[index] = last_group
            except Exception as err:
                logger.error(f"更新群信息失败:{err}")

        ret = self.groupx.post_groups(
            self.robot_account, self.robot_user_nickname, chatrooms
        )
        logger.info(
            f"post groups to server:位置:{self.postGroupsPos}, 共:{len(self.chatrooms)}, 返回数组长度:{len(ret)}"
        )
        self._set_remark_name_chatrooms(ret)
        return ret

    def _get_friends(self, session_id, start_timestamp=0, limit=9999):
        c = self._conn.cursor()
        c.execute(
            "SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?",
            (session_id, start_timestamp, limit),
        )
        return c.fetchall()

    def _get_friend(self, selfNickName, NickName):
        c = self._conn.cursor()
        c.execute(
            "SELECT * FROM friends_records WHERE selfNickName=? and NickName=?",
            (selfNickName, NickName),
        )
        return c.fetchone()
