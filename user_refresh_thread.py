# encoding:utf-8

from hashlib import md5
import json
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

        # 创建子线程
        t = threading.Thread(target=self.timer_sub_thread)
        t.setDaemon(True)
        t.start()

    # 定义子线程函数
    def timer_sub_thread(self):
        #延迟5秒后再检测，让初始化任务执行完
        time.sleep(15)
        #检测是否重新登录了
        self.isRelogin = False

        while True:
            # 定时检测
            self.timerCheck()
            #time.sleep(int(600)) # 600秒检测一次
            time.sleep(int(10)) # 调试时

    #定时检查
    def timerCheck(self):
        #检测是否重新登录了
        self.check_isRelogin()
        logger.info("定时检查,Bot UserName 为 {}".format(self.robot_user_id))
        #重新登录、未登录，均跳过
        if self.isRelogin:
            return
        logger.info("服务器已重新登录,Bot UserName 更新为 {}".format(self.robot_user_id))


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
            temp_isRelogin =True
            #取出任务中的一个模型
            # if self.timeTasks is not None and len(self.timeTasks) > 0:
            #     model : TimeTaskModel = self.timeTasks[0]
            #     temp_isRelogin = self.robot_user_id != model.toUser_id

            if temp_isRelogin:
                #更新为重新登录态
                self.isRelogin = True
                #等待登录完成
                time.sleep(3)

                #更新userId
                self.updateAllIds()

                #更新为非重新登录态
                self.isRelogin = False
        else:
            #置为重新登录态
            self.isRelogin = True
    def updateAllIds(self):
        self.saveFriends2DB()
        self.saveGroups2DB()
        self.postFriends2Groupx()
        self.postGroups2Groupx()

    def saveFriends2DB(self):
        #好友处理
        try:
            #获取好友列表
            friends = itchat.get_friends(update=True)[0:]
            
            c = self._conn.cursor()
            logger.debug("[saveFriends2DB] insert record: {} 条" .format(len(friends)))
            for friend in friends:
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
            friends = itchat.get_friends(update=True)[self.postFriendsPos:self.postFriendsPos+100]
            self.postFriendsPos += 100
            if(len(friends) < 100):
                self.postFriendsPos = 0
            
            json_data = {
                "payload": {
                    'NickName': self.robot_user_nickname,
                    'UserName': self.robot_user_id,
                    'friends': friends
                },
                "params": {
                    "addr": "0xb8F33dAb7b6b24F089d916192E85D7403233328A",
                    "random": "a9a58d316a16206ca2529720d01f8a9d10779eb330902f4ec05cf358a3418a9f",
                    "nonce": "1a9b1b1d9e854196143504b776b65e9fb5c87fe4930466a8fe68763fa6e48aed",
                    "ts": "1680592645793",
                    "hash": "0xc324d54dc3f613b8b33ce60d3085b5fc16b9012fa1df733361b370fec663bc67",
                    "method": 2,
                    "msg": "Please sign this message"
                },
                "sig": "825ccf873738de91a77b0de19b0f2db7e549efcca36215743c184197173967d770b141201651b21d6d89d27dc8d6cde6ccdc3151af67ed29b5cdaed2cecf3950"
            }

            post_url = self._config.get("groupx_host_url")+'/v1/wechat/itchat/user/friends/'
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            ret = response.text
            print("post friends to groupx api:",self.postFriendsPos,len(friends), ret)
            return ret
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
            
    def saveGroups2DB(self):
        #群组
        try:
            #群聊 （id组装 旧 ：新）
            chatrooms = itchat.get_chatrooms()
            c = self._conn.cursor()
            logger.debug("[saveGroups2DB] insert record: {} 条" .format(len(chatrooms)))
            for chatroom in chatrooms:
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
            chatrooms = itchat.get_chatrooms()[self.postGroupsPos:self.postGroupsPos+100]
            self.postGroupsPos += 100
            if(len(chatrooms) < 100):
                self.postGroupsPos = 0            
                
            json_data = {
                "payload": {
                    'NickName': self.robot_user_nickname,
                    'UserName': self.robot_user_id,
                    'groups': chatrooms
                },
                "params": {
                    "addr": "0xb8F33dAb7b6b24F089d916192E85D7403233328A",
                    "random": "a9a58d316a16206ca2529720d01f8a9d10779eb330902f4ec05cf358a3418a9f",
                    "nonce": "1a9b1b1d9e854196143504b776b65e9fb5c87fe4930466a8fe68763fa6e48aed",
                    "ts": "1680592645793",
                    "hash": "0xc324d54dc3f613b8b33ce60d3085b5fc16b9012fa1df733361b370fec663bc67",
                    "method": 2,
                    "msg": "Please sign this message"
                },
                "sig": "825ccf873738de91a77b0de19b0f2db7e549efcca36215743c184197173967d770b141201651b21d6d89d27dc8d6cde6ccdc3151af67ed29b5cdaed2cecf3950"
            }

            post_url = self._config.get("groupx_host_url")+'/v1/wechat/itchat/user/groups/'
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            ret = response.text
            print("post groups to groupx api:", self.postGroupsPos,len(chatrooms),ret)
            return ret
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
    def _get_friends(self, session_id, start_timestamp=0, limit=9999):
        c = self._conn.cursor()
        c.execute("SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?", (session_id, start_timestamp, limit))
        return c.fetchall()