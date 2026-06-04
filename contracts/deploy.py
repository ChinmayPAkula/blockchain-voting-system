import json
import os
from pathlib import Path
from dotenv import load_dotenv
from solcx import compile_standard, install_solc
from web3 import Web3

# Load .env from root
load_dotenv(dotenv_path=Path("../.env"))

# ==================== CONFIGURATION ====================
GANACHE_RPC = "http://127.0.0.1:7545"
SOLC_VERSION = "0.8.0"
CONTRACT_FILE = "VotingContract.sol"
KEYS_DIR = Path("../keys")

# ==================== CONNECT TO GANACHE ====================
w3 = Web3(Web3.HTTPProvider(GANACHE_RPC))
if not w3.is_connected():
    raise RuntimeError("Cannot connect to Ganache. Is it running?")
print(f"✓ Connected to Ganache")

# ==================== LOAD ADMIN KEY ====================
admin_private_key = os.getenv("GANACHE_ADMIN_PRIVATE_KEY")
admin_account = w3.eth.account.from_key(admin_private_key)
print(f"✓ Admin address: {admin_account.address}")

# ==================== LOAD VOTER ADDRESSES ====================
with open("../addresses.json", "r") as f:
    addresses = json.load(f)

voter_addresses = addresses["voter_addresses"]
print(f"✓ Loaded {len(voter_addresses)} voter addresses")

# ==================== COMPILE CONTRACT ====================
print("\nCompiling VotingContract.sol...")
install_solc(SOLC_VERSION)

with open(CONTRACT_FILE, "r") as f:
    contract_source = f.read()

compiled = compile_standard({
    "language": "Solidity",
    "sources": {
        CONTRACT_FILE: {"content": contract_source}
    },
    "settings": {
        "outputSelection": {
            "*": {"*": ["abi", "evm.bytecode"]}
        }
    }
}, solc_version=SOLC_VERSION)

# Debug
print("Compiled keys:", list(compiled["contracts"].keys()))
print("Contract keys:", list(compiled["contracts"][CONTRACT_FILE].keys()))

# Extract ABI and bytecode
contract_data = compiled["contracts"][CONTRACT_FILE]["VotingContract"]
abi = contract_data["abi"]
bytecode = contract_data["evm"]["bytecode"]["object"]

print(f"ABI length: {len(abi)}")

# Save ABI for oracle.py
with open("../VotingContract.json", "w") as f:
    json.dump({"abi": abi}, f, indent=2)
print(f"✓ ABI saved to VotingContract.json")

# ==================== DEPLOY CONTRACT ====================
print("\nDeploying contract to Ganache...")

VotingContract = w3.eth.contract(abi=abi, bytecode=bytecode)

tx = VotingContract.constructor(voter_addresses).build_transaction({
    "from": admin_account.address,
    "nonce": w3.eth.get_transaction_count(admin_account.address),
    "gas": 3000000,
    "gasPrice": w3.eth.gas_price,
})

signed_tx = w3.eth.account.sign_transaction(tx, admin_private_key)
tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

contract_address = receipt.contractAddress
print(f"✓ Contract deployed at: {contract_address}")

# Save contract address for oracle.py
with open("../contract_address.txt", "w") as f:
    f.write(contract_address)
print(f"✓ Address saved to contract_address.txt")

print("\n" + "="*60)
print("DEPLOYMENT COMPLETE")
print("="*60)
print(f"Contract address: {contract_address}")
print(f"Admin address:    {admin_account.address}")
print(f"Voters registered: {len(voter_addresses)}")
print("\nNext step: run oracle.py")