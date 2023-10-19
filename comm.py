
def makeGroupReq(payload):
    json_data = {
        'payload': payload,
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
    return json_data