import datetime


class UserManager:
    def __init__(self):
        self.user_knowledge = {}

    def should_update(self, user_id):
        if user_id in self.user_knowledge:
            last_update_time = self.user_knowledge[user_id]['last_update']
            time_difference = datetime.datetime.now() - last_update_time
            return time_difference.total_seconds() > 24 * 60 * 60
        return True

    def update_knowledge(self, user_id, new_knowledge):
        if self.should_update(user_id):
            self.user_knowledge[user_id] = {'know': new_knowledge, 'last_update': datetime.datetime.now()}
            self.cleanup()
    def get_knowledge(self, user_id):
        return self.user_knowledge[user_id]['know']
    def cleanup(self):
        current_time = datetime.datetime.now()
        # 循环遍历用户知识
        for user_id, knowledge_info in list(self.user_knowledge.items()):
            last_update_time = knowledge_info['last_update']
            # 计算时间差
            time_difference = current_time - last_update_time
            # 超过 3 天没有更新的知识进行删除
            if time_difference.total_seconds() > 3 * 24 * 60 * 60:
                del self.user_knowledge[user_id]

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
