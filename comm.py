
def makeGroupReq(account,payload):
    json_data = {
        'payload': payload,
        "params": {
                "addr": account if account else "0x0000000000000000000000000000000000000000",
                "random": "a9a58d316a16206ca2529720d01f8a9d10779eb330902f4ec05cf358a3418a9f",
                "nonce": "1a9b1b1d9e854196143504b776b65e9fb5c87fe4930466a8fe68763fa6e48aed",
                "ts": "1680592645793",
                "hash": "0xc324d54dc3f613b8b33ce60d3085b5fc16b9012fa1df733361b370fec663bc67",
                "method": 2,
                "msg": "Please sign this message"
            },
        "sig": "825ccf873738de91a77b0de19b0f2db7e549efcca36215743c184197173967d770b141201651b21d6d89d27dc8d6cde6ccdc3151af67ed29b5cdaed2cecf3950"
    }
    return json_data

import re

def is_eth_address(address):
    # 以太坊地址的正则表达式
    ethereum_address_pattern = re.compile(r'^0x[1-9a-fA-F][0-9a-fA-F]{39}$')
    
    # 使用正则表达式匹配
    return bool(ethereum_address_pattern.match(address))

def test():
    # 示例用法
    valid_address = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
    invalid_address_all_zeros = "0x0000000000000000000000000000000000000000"
    invalid_address_starting_with_zero = "0x0123456789abcdef0123456789abcdef01234567"

    print(f"{valid_address} 是否有效：{is_eth_address(valid_address)}")
    print(f"{invalid_address_all_zeros} 是否有效：{is_eth_address(invalid_address_all_zeros)}")
    print(f"{invalid_address_starting_with_zero} 是否有效：{is_eth_address(invalid_address_starting_with_zero)}")
    
    # 0x742d35Cc6634C0532925a3b844Bc454e4438f44e 是否有效：True
    # 0x0000000000000000000000000000000000000000 是否有效：False
    # 0x0123456789abcdef0123456789abcdef01234567 是否有效：False
#test()
EthZero = "0x0000000000000000000000000000000000000000"