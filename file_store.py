import os
import sqlite3
import hashlib
from common.log import logger


class MyFileStory(object) :
    def __init__(self):
        self.curdir = os.path.dirname(__file__)
        self.saveFolder = os.path.join(self.curdir, 'saved')
        self.saveSubFolders = {'webwxgeticon': 'icons', 'webwxgetheadimg': 'headimgs',      'webwxgetmsgimg': 'msgimgs', 'webwxgetvideo': 'videos',
        'webwxgetvoice': 'voices', '_showQRCodeImg': 'qrcodes'}

    def _save_file(self, filename, data, api=None):
        fn = filename
        if self.saveSubFolders[api]:
            dirName = os.path.join(self.saveFolder, self.saveSubFolders[api])
            if not os.path.exists(dirName):
                os.makedirs(dirName)
            fn = os.path.join(dirName, filename)
            logger.info('Saved file: %s' % fn)
            with open(fn, 'wb') as f:
                f.write(data)
                f.close()
        return fn, dirName
    def get_avatar_file(self, user_id):
        dirName = os.path.join(self.saveFolder, self.saveSubFolders['webwxgetheadimg'])
        avatar_file = os.path.join(dirName, f'headimg-{user_id}.png')
        if os.path.exists(avatar_file):
            return avatar_file
        return None
    # 使用硬链接保存文件,实际文件名为md5,防止同一个图片多次下载
    def save_avatar_file(self, user_id, fileBody) :
        # 计算 MD5 哈希值
        md5 = hashlib.md5(fileBody)
        md5_name = f'headimg-{md5.hexdigest()}.png'
        fn, dirName = self._save_file(md5_name, fileBody, 'webwxgetheadimg')

        os.symlink(fn, os.path.join(dirName, f'headimg-{user_id}.png'))
        return fn
