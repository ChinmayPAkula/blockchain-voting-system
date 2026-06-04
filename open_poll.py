import os
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3
import json

load_dotenv()

w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:7545"))

admin_private_key = os.getenv("GANACHE_ADMIN_PRIVATE_KEY")
admin_account = w3.eth.account.from_key(admin_private_key)

with open("VotingContract.json") as f:
    abi = json.load(f)["abi"]

with open("contract_address.txt") as f:
    address = f.read().strip()

contract = w3.eth.contract(address=address, abi=abi)

tx = contract.functions.openPoll().build_transaction({
    "from": admin_account.address,
    "nonce": w3.eth.get_transaction_count(admin_account.address),
    "gas": 100000,
    "gasPrice": w3.eth.gas_price,
})

signed = w3.eth.account.sign_transaction(tx, admin_private_key)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

print(f"✓ Poll opened. Tx: {tx_hash.hex()}")
print(f"  Block: {receipt.blockNumber}")