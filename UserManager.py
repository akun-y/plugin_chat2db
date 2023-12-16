import datetime

from lib import itchat
from plugins.plugin_chat2db.comm import EthZero, is_eth_address
from common.log import logger


# 用于管理所有用户的知识库及用户基本信息,按时更新信息.
class UserManager:
    def __init__(self, groupx):
        self.groupx = groupx
        self.user_knowledge = {}
        self.doctor_of_user = {}
        self.doctor_of_group = {}
        self.group_info = {}
        self.users = {}

    def should_update(self, user_id, user_session=None):
        if user_id in self.user_knowledge:
            if user_session:
                session_len = len(user_session)
                logger.info(f"===>user_session 长度 {session_len}")
                if session_len > 50:# 超过50条就删除2条并更新know
                    user_session.pop(0)
                    user_session.pop(0)
                    logger.info("用户session超过50条，更新知识库！")
                    return True 

            last_update_time = self.user_knowledge[user_id]["last_update"]
            time_difference = datetime.datetime.now() - last_update_time
            return time_difference.total_seconds() > 24 * 60 * 60
        return True

    def update_knowledge(self, user_id, new_knowledge):
        if self.should_update(user_id):
            self.user_knowledge[user_id] = {
                "know": new_knowledge,
                "last_update": datetime.datetime.now(),
            }
            self.cleanup()

    def get_knowledge(self, user_id):
        return self.user_knowledge[user_id]["know"]

    def cleanup(self):
        current_time = datetime.datetime.now()
        # 循环遍历用户知识
        for user_id, knowledge_info in list(self.user_knowledge.items()):
            last_update_time = knowledge_info["last_update"]
            # 计算时间差
            time_difference = current_time - last_update_time
            # 超过 3 天没有更新的知识进行删除
            if time_difference.total_seconds() > 3 * 24 * 60 * 60:
                del self.user_knowledge[user_id]

    # -----------------------------------------
    # 用户
    def get_user(self, user_id):
        user = self.users.get(user_id, None)
        if user:
            return user

        user = itchat.update_friend(user_id)
        if user:
            self.users[user_id] = user
            return user
        return None

    # -----------------------------------------
    # 对应的医生信息
    def _fetch_doctor_of_user(self, account, agent, user_id, user_name):
        result = self.groupx.get_my_doctor_info(
            account=account, agent=agent, user_id=user_id, user_name=user_name
        )
        self.doctor_of_user[user_id] = result
        return self.doctor_of_user[user_id]

    def get_my_doctor(self, account, agent, user_id, user_name):
        if not account:
            account = EthZero
        doctor = self.doctor_of_user.get(user_id, None)
        return (
            doctor
            if doctor
            else self._fetch_doctor_of_user(account, agent, user_id, user_name)
        )

    def set_my_doctor(self, user_id, doctor_account):
        if not user_id:
            return
        if is_eth_address(doctor_account):
            self.doctor_of_user[user_id] = doctor_account

    def _fetch_doctor_of_group(self, group_id):
        result = self.groupx.get_doctor_of_group(group_id)
        self.doctor_of_group[group_id] = result
        return self.doctor_of_group[group_id]

    def get_doctor_of_group(self, group_id):
        doctor = self.doctor_of_group.get(group_id, None)
        return doctor if doctor else self._fetch_doctor_of_group(group_id)

    # -----------------------------------------
    # 微信群信息
    def _fetch_group_info(self, group_id):
        result = self.groupx.get_wxgroup_info(group_id)
        self.group_info[group_id] = result
        return self.group_info[group_id]

    def get_group_info(self, group_id):
        group = self.group_info.get(group_id, None)

        if group:
            return group
        return group if group else self._fetch_group_info(group_id)

    # -----------------------------------------


# # 示例用法
# user_manager = UserManager()

# # 第一次写入知识
# user_manager.update_knowledge('user123', {'some_data': 'value'})

# # 等待 25 小时后再次写入知识
# user_manager.update_knowledge('user123', {'updated_data': 'new_value'})

# # 第一次写入知识到 user456
# user_manager.update_knowledge('user456', {'data': 'value'})

# # 立即再次写入知识到 user456，但由于时间间隔小于 24 小时，不会更新
# user_manager.update_knowledge('user456', {'updated_data': 'new_value'})

# # 等待 3 天后，再次写入知识到 user456
# user_manager.user_knowledge['user456']['last_update'] -= datetime.timedelta(days=3)
# user_manager.update_knowledge('user456', {'updated_data': 'new_value'})

# # 清理过期知识
# user_manager.cleanup()

# print(user_manager.user_knowledge)
