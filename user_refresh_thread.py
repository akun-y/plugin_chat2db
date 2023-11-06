# encoding:utf-8

from hashlib import md5
import json
from plugins.plugin_chat2db.comm import makeGroupReq
from plugins.timetask.Tool import ExcelTool
from plugins.timetask.Tool import TimeTaskModel
from common.log import logger
import time
import arrow
import threading
from typing import List
from plugins.timetask.config import conf, load_config
from lib import itchat
from lib.itchat.content import *
import config as RobotConfig
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

        self.robot_user_id = ""
        self.robot_user_nickname=""

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
                
                
            
            time.sleep(int(600)) # 600秒检测一次
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
        #好友处理
        try:
            #获取好友列表,每次100条,越界后又从0开始
            if(len(self.friends) < 1): self.friends = itchat.get_friends(update=True)

            friends = self.friends[self.postFriendsPos:self.postFriendsPos+100]
            self.postFriendsPos += 100
            if(len(friends) < 100):
                #全部好友都发送完成了
                self.postFriendsPos = 0
            else :
                # 每隔5秒执行一次,知道好友列表全部发送完成
                threading.Timer(5.0, self.postFriends2Groupx).start()

            json_data = makeGroupReq('',{
                    'NickName': self.robot_user_nickname,
                    'UserName': self.robot_user_id,
                    'friends': friends
                })
            post_url = self._config.get("groupx_host_url")+'/v1/wechat/itchat/user/friends/'
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            ret = response.text
            print("post friends to groupx api:", self.postFriendsPos, len(friends), ret)
            return ret=='"ok"'
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
        return False;

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
        #好友处理
        try:
            #获取群列表,每次100条,越界后又从0开始
            if len(self.chatrooms) < 1: self.chatrooms = itchat.get_chatrooms()

            chatrooms = self.chatrooms[self.postGroupsPos:self.postGroupsPos+100]
            self.postGroupsPos += 100
            if(len(chatrooms) < 100):
                self.postGroupsPos = 0
            else:
                # 每隔8秒执行一次,直到好友列表全部发送完成
                threading.Timer(8.0, self.postGroups2Groupx).start()

            json_data = makeGroupReq('',{
                    'NickName': self.robot_user_nickname,
                    'UserName': self.robot_user_id,
                    'groups': chatrooms,
                })

            post_url = self._config.get("groupx_host_url")+'/v1/wechat/itchat/user/groups/'
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            ret = response.text
            print("post groups to groupx api:", self.postGroupsPos, len(chatrooms), ret)
            return ret == '"ok"'
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
        return False
    def _get_friends(self, session_id, start_timestamp=0, limit=9999):
        c = self._conn.cursor()
        c.execute("SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?", (session_id, start_timestamp, limit))
        return c.fetchall()
    def _get_friend(self, selfNickName, NickName):
        c = self._conn.cursor()
        c.execute("SELECT * FROM friends_records WHERE selfNickName=? and NickName=?", (selfNickName, NickName))
        return c.fetchone()
