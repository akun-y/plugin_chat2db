# encoding:utf-8

from hashlib import md5
import json
from plugins.plugin_chat2db.head_img_manager import HeadImgManager
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_chat2db.comm import EthZero, makeGroupReq
from common.log import logger
import time
import arrow
import threading
from typing import List
from lib import itchat
from lib.itchat.content import *
import config as RobotConfig

from plugins.plugin_chat2db.api_tentcent import ApiTencent
import requests
try:
    from channel.wechatnt.ntchat_channel import wechatnt
except Exception as e:
    print(f"未安装ntchat: {e}")


#定时检测用户联系人及群组信息,同步最新的 wechat UserName


class UserRefreshThread(object):
    def __init__(self, conn, config):
        super().__init__()
        #保存定时任务回调
        self._config = config
        self._conn = conn

        self.groupxHostUrl = self._config.get("groupx_host_url")
        self.groupx = ApiGroupx(self.groupxHostUrl)
        self.tencent = ApiTencent(self.groupxHostUrl)
        self.img_service = HeadImgManager(conn, self.groupxHostUrl)

        self.robot_account =  config.get("account")
        self.robot_user_id = ""
        self.robot_user_nickname=config.get("name")

        self.isRelogin = False

        self.postFriendsPos = 0
        self.postGroupsPos = 0

        self.friends =[]
        self.chatrooms = []
        # 创建子线程
        t = threading.Thread(target=self.timer_sub_thread)
        t.setDaemon(True)
        t.start()

    # 定义子线程函数
    def timer_sub_thread(self):
        #延迟15秒后再检测，让初始化任务执行完
        time.sleep(15)
        #检测是否重新登录了
        self.isRelogin = False

        while True:
            # 定时检测
            self.timerCheck()
            # 群组列表有没有增减
            chatrooms = itchat.get_chatrooms()
            if(len(chatrooms) != len(self.chatrooms)):
                self.chatrooms = chatrooms
                self.updateAllIds()

            time.sleep(int(100*60)) # 100*60秒(100分钟)检测一次
            #time.sleep(int(10)) # 调试时

    #定时检查,检测机器人是否重新登录了(服务器重启时变化)
    def timerCheck(self):
        #检测是否重新登录了
        self.check_isRelogin()
        #重新登录、未登录，均跳过
        if self.isRelogin:
            logger.warn("服务器已重新登录,Bot UserName 更新为 {}".format(self.robot_user_id))
            return
        logger.info("定时检测,bot UserName无变化 {}".format(self.robot_user_id))


#检测是否重新登录了
    def check_isRelogin(self):
        #机器人ID
        self.robot_user_id = ""
        #通道
        channel_name = RobotConfig.conf().get("channel_type", "wx")
        if channel_name == "wx":
            self.robot_user_id = itchat.instance.storageClass.userName
            self.robot_user_nickname = itchat.instance.storageClass.nickName
        elif channel_name == "ntchat":
            try:
                login_info = wechatnt.get_login_info()
                nickname = login_info['nickname']
                user_id = login_info['wxid']
                self.robot_user_id = user_id
                self.robot_user_nickname =nickname
            except Exception as e:
                print(f"获取 ntchat的 userid 失败: {e}")
                #nt
                self.isRelogin = False
                return
        else:
            #其他通道，默认不更新用户ID
            self.isRelogin = False
            return

        #登录后
        if self.robot_user_id is not None and len(self.robot_user_id) > 0:
            #NTChat的userID不变
            if channel_name == "ntchat":
                self.isRelogin = False
                return

            #temp_isRelogin =True #调试时才用

            #取出好友中的机器人用户,
            myself = self._get_friend(self.robot_user_nickname, self.robot_user_nickname)
            if myself is None:
                myselfUserName=""
            else:
                myselfUserName = myself[0]
            #     model : TimeTaskModel = self.timeTasks[0]
            temp_isRelogin = self.robot_user_id != myselfUserName

            if temp_isRelogin:
                #更新为重新登录态
                self.isRelogin = True
                #等待登录完成
                time.sleep(10)

                #更新userId
                self.updateAllIds()

                #更新为非重新登录态
                self.isRelogin = False
        else:
            #置为重新登录态
            self.isRelogin = True
    def updateAllIds(self):
        logger.info("更新用户ID,Friends, Groups")
        if(self.postFriends2Groupx()):
            self.saveFriends2DB()
        if(self.postGroups2Groupx()):
            self.saveGroups2DB()
    def saveFriends2DB(self):
        #好友处理
        try:
            #获取好友列表
            if(len(self.friends) < 1):
                self.friends = itchat.get_friends(update=True)

            c = self._conn.cursor()
            logger.debug("[saveFriends2DB] insert record: {} 条" .format(len(self.friends)))
            for friend in self.friends:
                c.execute("INSERT OR REPLACE INTO friends_records VALUES (?,?,?,?,?,?)", (
                    self.robot_user_id, self.robot_user_nickname, '',
                    friend.UserName, friend.NickName, friend.HeadImgUrl))

            self._conn.commit()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")

    def postFriends2Groupx(self):
        #获取好友列表,每次100条,越界后又从0开始
        if(len(self.friends) < 1): self.friends = itchat.get_friends(update=True)

        end = self.postFriendsPos + 100
        if(end > len(self.friends)) : end = len(self.friends) -1
        friends = self.friends[self.postFriendsPos:end]
        logger.info(f"post friends to groupx:{self.postFriendsPos}->{end},本次:{len(friends)}个,总共:{len(self.friends)}")

        self.postFriendsPos += 100
        if(len(friends) < 100):
            #全部好友都发送完成了
            self.postFriendsPos = 0
        else :
            # 每隔5秒执行一次,直到好友列表全部发送完成
            threading.Timer(5.0, self.postFriends2Groupx).start()

        ret = self.groupx.post_friends(self.robot_account, self.robot_user_nickname, self.robot_user_id, friends)
        if ret is False:
            logger.error(f"post friends to groupx failed")
            return False
        else:
            logger.info(f"post friends to groupx success")

        filtered_data = [item for item in ret if item.get('friendAccount')]
        logger.info(f"post friends have account :{len(filtered_data)}")
        # 遍历字典的所有子项，为每个子项设置account字段
        for friend in filtered_data:
            _usr = itchat.update_friend(friend.get('friendUserName'))
            account = _usr.get('RemarkName', None)
            #ethAddr存在到RemarkName 中
            retAccount = friend.get('friendAccount', None)
            if(retAccount and account != retAccount):
                #更新account到 RemarkName中
                logger.info(f'更新好友 {_usr.get("NickName")} account 为 {retAccount}')
                _usr.set_alias(retAccount)
                _usr.update()
                itchat.dump_login_status()

        return ret

    def saveGroups2DB(self):
        #群组
        try:
            #群聊 （id组装 旧
            if len(self.chatrooms) < 1: self.chatrooms = itchat.get_chatrooms()

            c = self._conn.cursor()
            logger.debug("[saveGroups2DB] insert record: {} 条" .format(len(self.chatrooms)))
            for chatroom in self.chatrooms:
                c.execute("INSERT OR REPLACE INTO groups_records VALUES (?,?,?,?,?,?,?,?)", (
                chatroom.Self.UserName, chatroom.Self.NickName, chatroom.Self.DisplayName,
                chatroom.UserName, chatroom.NickName, chatroom.HeadImgUrl,
                chatroom.get('PYQuanPin'), chatroom.get('EncryChatRoomId')))
            self._conn.commit()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("群聊列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
    def postGroups2Groupx(self):
        #获取群列表,每次100条,越界后又从0开始
        if len(self.chatrooms) < 1: self.chatrooms = itchat.get_chatrooms()

        chatrooms = self.chatrooms[self.postGroupsPos:self.postGroupsPos+100]
        self.postGroupsPos += 100
        if(len(chatrooms) < 100):
            self.postGroupsPos = 0
        else:
            # 每隔8秒执行一次,直到好友列表全部发送完成
            threading.Timer(8.0, self.postGroups2Groupx).start()

        update_chatroom = 0
        for index, value in enumerate(chatrooms):
            value['HeadImgUrl'] = self.img_service.get_head_img_url(value.get('UserName'), True)
            if(value['MemberList']== []):
                room = itchat.update_chatroom(value['UserName'], True)
                chatrooms[index] = room
                update_chatroom += 1
                room.update()
                logger.info(f"从腾讯服务器获取群最新信息：{room['NickName']} 成员:{len(room['MemberList'])}个)")
            logger.info(f'群:{value.NickName}({len(value["MemberList"])})头像:{value.HeadImgUrl}')
        if update_chatroom>0:
            logger.info(f"更新{update_chatroom}个群信息成功,保存登录状态")
            itchat.dump_login_status()

        ret = self.groupx.post_groups(self.robot_account, self.robot_user_nickname, self.robot_user_id, chatrooms)
        logger.info(f"post groups to groupx api:{self.postGroupsPos}, {len(chatrooms)}, {ret}")
        return ret

    def _get_friends(self, session_id, start_timestamp=0, limit=9999):
        c = self._conn.cursor()
        c.execute("SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?", (session_id, start_timestamp, limit))
        return c.fetchall()
    def _get_friend(self, selfNickName, NickName):
        c = self._conn.cursor()
        c.execute("SELECT * FROM friends_records WHERE selfNickName=? and NickName=?", (selfNickName, NickName))
        return c.fetchone()
