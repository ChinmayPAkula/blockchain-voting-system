import os
from dotenv import load_dotenv
from pathlib import Path
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3
from eth_abi import encode
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

# Load voter 0 key
with open("keys/voter_0.key") as f:
    voter_key = f.read().strip()
voter_account = Account.from_key(voter_key)

# Get current block number
block_number = w3.eth.block_number

# Hash exactly like Solidity does
raw_hash = w3.solidity_keccak(
    ['address', 'string'],
    [voter_account.address, 'PARTY_A']
)

# Add Ethereum prefix
message = encode_defunct(primitive=raw_hash)
signed = voter_account.sign_message(message)
signature = signed.signature

print(f"Voter address: {voter_account.address}")
print(f"Block number: {block_number}")
print(f"Raw hash: {raw_hash.hex()}")
print(f"Signature length: {len(signature)}")

# Cast vote
tx = contract.functions.castVote(
    voter_account.address,
    "PARTY_A",
    signature
).build_transaction({
    'from': admin_account.address,
    'nonce': w3.eth.get_transaction_count(admin_account.address),
    'gas': 300000,
    'gasPrice': w3.eth.gas_price,
})

signed_tx = w3.eth.account.sign_transaction(tx, admin_private_key)
tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

print(f"Vote cast. Status: {receipt.status}")
print(f"Tx hash: {tx_hash.hex()}")

counts = contract.functions.getAllVoteCounts().call()
print(f"Party A: {counts[0]}, B: {counts[1]}, C: {counts[2]}, D: {counts[3]}")