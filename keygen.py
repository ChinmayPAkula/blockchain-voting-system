"""
keygen.py - Generate voter and admin keypairs for the blockchain voting system.

WHY THIS EXISTS:
- Creates 10 Ethereum keypairs (one per voter) using ECDSA secp256k1
- Creates 1 admin keypair (deploys contract, opens/closes polls)
- Saves private keys to keys/ folder (source of truth for signing)
- Returns public addresses (registered in smart contract)

CRYPTOGRAPHY:
- eth-account uses secp256k1 (same as Bitcoin/Ethereum)
- Each Account has: private_key, address (public identifier), sign_message() method
- Private keys NEVER leave disk unless oracle.py reads them to sign a vote

THREAT MODEL:
- Arduino is untrusted (no crypto, just input capture)
- keys/ folder is trusted (file permissions should restrict read)
- oracle.py is trusted (reads keys, signs votes)
- Smart contract is the immutable ledger (source of truth)

CONFERENCE NOTES:
- "How do you prove non-repudiation?" → Voter #3's signature matches voter #3's address
- "What if someone steals a private key?" → That voter can vote unlimited times; mitigation is physical RFID card control + paper trail
"""

import os
import json
from eth_account import Account

# Configuration
NUM_VOTERS = 10
KEYS_DIR = "keys"

def ensure_keys_dir():
    """Create keys/ folder if it doesn't exist."""
    if not os.path.exists(KEYS_DIR):
        os.makedirs(KEYS_DIR)
        print(f"✓ Created {KEYS_DIR}/ directory")
    else:
        print(f"✓ {KEYS_DIR}/ directory exists")


def generate_keypair(label: str) -> dict:
    """
    Generate a single Ethereum keypair using eth-account.
    
    WHY eth-account.Account.create():
    - Uses cryptographically secure random number generation
    - Returns Account object with .key (private key) and .address (public address)
    - The address is deterministic from the private key (can't be changed)
    - We DON'T set a password because we're storing in files; production would encrypt
    
    Args:
        label: Human-readable name (e.g., "voter_0", "admin")
    
    Returns:
        dict with 'label', 'private_key', 'address'
    """
    account = Account.create()
    
    return {
        "label": label,
        "private_key": account.key.hex(),  # Convert to hex string (0x prefix)
        "address": account.address  # Already a string like "0x742d35Cc6634C0532925a3b844Bc9e7595f42bE"
    }


def save_keypair(keypair: dict) -> str:
    """
    Save a single keypair to keys/{label}.key
    
    WHY this format:
    - Plain hex string, one per file
    - Simple to read in oracle.py: just open and read()
    - File permissions can restrict read (chmod 600 on Linux, NTFS ACL on Windows)
    - NOT a JSON file (those are for the blockchain state, not crypto material)
    
    Args:
        keypair: dict with 'label', 'private_key', 'address'
    
    Returns:
        filepath where key was saved
    """
    filepath = os.path.join(KEYS_DIR, f"{keypair['label']}.key")
    
    with open(filepath, 'w') as f:
        f.write(keypair['private_key'])
    
    print(f"  ✓ {filepath:<30} Address: {keypair['address']}")
    
    return filepath


def generate_all_keys():
    """
    Main orchestration: generate 10 voter keys + 1 admin key.
    
    OUTPUT:
    - keys/voter_0.key through keys/voter_9.key (10 files, each contains hex private key)
    - keys/admin.key (1 file)
    - addresses.json (next step: copy these addresses into VotingContract.sol)
    """
    ensure_keys_dir()
    
    print("\n" + "="*70)
    print("GENERATING VOTER KEYPAIRS (10 voters)")
    print("="*70)
    
    voter_keypairs = []
    for i in range(NUM_VOTERS):
        keypair = generate_keypair(f"voter_{i}")
        save_keypair(keypair)
        voter_keypairs.append(keypair)
    
    print("\n" + "="*70)
    print("GENERATING ADMIN KEYPAIR")
    print("="*70)
    
    admin_keypair = generate_keypair("admin")
    save_keypair(admin_keypair)
    
    # Save addresses to a reference file (for deploying contract)
    addresses_file = "addresses.json"
    addresses_data = {
        "voter_addresses": [kp['address'] for kp in voter_keypairs],
        "admin_address": admin_keypair['address'],
        "generated_at": __import__('datetime').datetime.now().isoformat()
    }
    
    with open(addresses_file, 'w') as f:
        json.dump(addresses_data, f, indent=2)
    
    print("\n" + "="*70)
    print(f"✓ KEYPAIR GENERATION COMPLETE")
    print("="*70)
    print(f"\n📋 Addresses saved to: {addresses_file}")
    print(f"\n🔑 Private keys saved to: {KEYS_DIR}/")
    print(f"   - voter_0.key through voter_9.key")
    print(f"   - admin.key")
    print("\n⚠️  NEXT STEPS:")
    print("   1. Copy voter_addresses from addresses.json")
    print("   2. Hardcode into VotingContract.sol registeredVoters[] array")
    print("   3. Deploy contract using admin.key")
    print("   4. Never commit keys/ folder to git!")
    
    return addresses_data


if __name__ == "__main__":
    generate_all_keys()