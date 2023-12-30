import json

from plugins.plugin_comm.comm import is_eth_address, is_valid_json


class RemarkNameInfo(object):

    def __init__(self, remark_name):
        self.data = {'account': '', 'object_id': ''}
        if isinstance(remark_name, str):
            if is_eth_address(remark_name):
                self.data['account'] = remark_name
            elif is_valid_json(remark_name):
                try:
                    # 解析 json 字符串出错时会跳过赋值语句
                    d = json.loads(remark_name)
                    self.data = d
                except Exception:
                    pass

    def set_account(self, account):
        if not isinstance(account, str):
            return
        self.data['account'] = account

    def set_object_id(self, object_id):
        if not isinstance(object_id, str):
            return
        self.data['object_id'] = object_id

    def get_account(self):
        return self.data['account']

    def get_object_id(self):
        return self.data['object_id']

    def get_remark_name(self):
        try:
            return json.dumps(self.data)
        except Exception:
            return ''
