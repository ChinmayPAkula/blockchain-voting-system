"""
oracle.py - Blockchain Voting Oracle

PURPOSE:
- Listen to Arduino on Serial port
- Parse VOTER_INDEX:X|VOTE:PARTY_Y format
- Load voter's private key from keys/voter_X.key
- Sign the vote using ECDSA (secp256k1)
- Call smart contract to record vote on blockchain
- Broadcast transaction to Ganache
- Log all errors and anomalies

THREAT MODEL:
- Arduino is UNTRUSTED: Can send garbage, duplicates, or be compromised
- This oracle is TRUSTED: Has access to private keys, signs votes
- Smart contract is IMMUTABLE: Source of truth on blockchain
- Private keys NEVER leave disk unless oracle.py explicitly reads them

SECURITY GUARANTEES:
1. Signature verification happens on-chain (contract checks signature)
2. Double voting prevented by contract's hasVoted mapping
3. All votes are immutable events on blockchain
4. Serial anomalies are logged (audit trail of what Arduino sent)

FLOW DIAGRAM:
Arduino → Serial String → Oracle Parsing → Private Key Load → ECDSA Sign → 
Web3.py Transaction → Ganache Smart Contract → Event Emission → Immutable Ledger

CONFERENCE TALKING POINTS:
- "Why doesn't Arduino sign?" Arduino can't do ECDSA fast, and if compromised, keys could leak.
- "How does signature verification work?" Contract uses ecrecover() to recover the signer from signature.
- "What if Serial is corrupted?" Oracle logs the error and skips; no transaction is sent.
"""

import serial
import json
import time
import logging
from pathlib import Path
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# ==================== CONFIGURATION ====================

SERIAL_PORT = "COM3"  # Change to your Arduino COM port (COM1-COM10 on Windows)
SERIAL_BAUD = 9600   # Match Arduino's Serial.begin(9600)

GANACHE_RPC = "http://127.0.0.1:7545"  # Local Ganache endpoint

KEYS_DIR = Path("keys")  # Where private keys are stored
CONTRACT_ABI_FILE = "VotingContract.json"  # ABI from compiled contract
CONTRACT_ADDRESS_FILE = "contract_address.txt"  # Address of deployed contract

VALID_PARTIES = {"PARTY_A", "PARTY_B", "PARTY_C", "PARTY_D"}
NUM_VOTERS = 10

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("voting_oracle.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ==================== WEB3 SETUP ====================

class Web3Manager:
    """
    Wrapper around Web3.py to interact with smart contract.
    
    WHY SEPARATE CLASS:
    - Encapsulates contract interaction
    - Easy to test (can mock this class)
    - Clear separation: Serial logic vs. Blockchain logic
    """
    
    def __init__(self, rpc_url: str, contract_abi_file: str, contract_address_file: str):
        """
        Connect to Ganache and load contract ABI.
        
        Args:
            rpc_url: Ganache RPC endpoint
            contract_abi_file: Path to VotingContract.json (ABI)
            contract_address_file: Path to file with contract address
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        # Verify connection to Ganache
        if not self.w3.is_connected():
            raise RuntimeError(f"Cannot connect to {rpc_url}. Is Ganache running?")
        
        logger.info(f"✓ Connected to Ganache at {rpc_url}")
        logger.info(f"  Block number: {self.w3.eth.block_number}")
        
        # Load contract ABI
        with open(contract_abi_file, 'r') as f:
            contract_data = json.load(f)
            self.contract_abi = contract_data.get("abi") or contract_data
        
        # Load contract address
        with open(contract_address_file, 'r') as f:
            self.contract_address = f.read().strip()
        
        # Instantiate contract
        self.contract = self.w3.eth.contract(
            address=self.contract_address,
            abi=self.contract_abi
        )
        
        logger.info(f"✓ Loaded VotingContract at {self.contract_address}")
    
    def is_poll_open(self) -> bool:
        """Check if poll is currently open on-chain."""
        try:
            return self.contract.functions.pollOpen().call()
        except Exception as e:
            logger.error(f"Error checking poll state: {e}")
            return False
    
    def submit_vote(self, voter_address: str, party: str, signature: bytes, admin_account: Account) -> str:
        """
        Submit a signed vote to the smart contract.
        
        WHY THIS FUNCTION:
        - Handles transaction creation, signing, and broadcasting
        - Waits for receipt (vote is on-chain)
        - Returns transaction hash (proof)
        
        Args:
            voter_address: The voter's Ethereum address (derived from private key)
            party: Party name (PARTY_A, PARTY_B, etc.)
            signature: ECDSA signature bytes (from oracle.sign_vote())
            admin_account: Admin account for paying gas (from admin.key)
        
        Returns:
            Transaction hash if successful, None if failed
        
        SECURITY NOTE:
        - Only admin pays gas (admin account signs the transaction)
        - But the vote is attributed to voter_address (via signature verification on-chain)
        - This is intentional: admin broadcasts, but contract verifies voter's signature
        """
        try:
            # Build transaction to call castVote()
            tx = self.contract.functions.castVote(
                voter_address,
                party,
                signature
            ).build_transaction({
                'from': admin_account.address,
                'nonce': self.w3.eth.get_transaction_count(admin_account.address),
                'gas': 300000,  # Adjust if needed
                'gasPrice': self.w3.eth.gas_price,
            })
            
            # Sign transaction with admin's private key
            signed_tx = self.w3.eth.account.sign_transaction(tx, admin_account.key)
            
            # Broadcast to Ganache
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Wait for receipt (vote is recorded on-chain)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt.status == 1:
                logger.info(f"✓ Vote recorded. Tx: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"✗ Transaction failed. Tx: {tx_hash.hex()}")
                return None
        
        except Exception as e:
            logger.error(f"Error submitting vote to contract: {e}")
            return None


# ==================== SIGNING LOGIC ====================

class VoteSigner:
    """
    Sign votes using voter's private key.
    
    WHY SEPARATE CLASS:
    - Encapsulates cryptographic operations
    - Easy to understand: voter key → sign → signature
    - Can be tested independently
    """
    
    def __init__(self, keys_dir: Path):
        """
        Args:
            keys_dir: Directory containing voter_X.key files
        """
        self.keys_dir = keys_dir
        self._key_cache = {}  # Cache loaded keys (for performance)
    
    def load_voter_key(self, voter_index: int) -> Account:
        """
        Load a voter's private key from disk and return an Account object.
        
        WHY:
        - Private keys stay on disk (never loaded into memory until needed)
        - Account object provides .sign_message() and .address properties
        - Cached to avoid repeated disk reads (performance)
        
        Args:
            voter_index: 0-9 (from Arduino VOTER_INDEX)
        
        Returns:
            eth_account.Account object with private key loaded
        
        Raises:
            FileNotFoundError: If key file doesn't exist
            ValueError: If private key is invalid
        """
        if voter_index in self._key_cache:
            return self._key_cache[voter_index]
        
        key_file = self.keys_dir / f"voter_{voter_index}.key"
        
        if not key_file.exists():
            raise FileNotFoundError(f"Key file not found: {key_file}")
        
        try:
            with open(key_file, 'r') as f:
                private_key_hex = f.read().strip()
            
            # Create Account object from private key
            account = Account.from_key(private_key_hex)
            self._key_cache[voter_index] = account
            
            logger.debug(f"Loaded voter_{voter_index} key: {account.address}")
            return account
        
        except Exception as e:
            logger.error(f"Error loading voter_{voter_index} key: {e}")
            raise
    
    def sign_vote(self, voter_account: Account, party: str, block_number: int) -> bytes:
        """
        Sign a vote using the voter's private key.
        
        HOW ECDSA SIGNING WORKS:
        1. Create a message: keccak256(voter_address + party_name + block_number)
        2. Sign the message with voter's private key (ECDSA secp256k1)
        3. Get signature bytes (r, s, v) where v is recovery ID
        4. Contract will call ecrecover(message, signature) to verify
        
        WHY THIS MESSAGE FORMAT:
        - voter_address: Proves this vote belongs to this voter
        - party_name: Proves the voter voted for this party
        - block_number: Prevents replay attacks (can't reuse signature in another block)
        
        Args:
            voter_account: Account object with private key loaded
            party: Party name (PARTY_A, PARTY_B, etc.)
            block_number: Current block number (from Web3)
        
        Returns:
            Signature bytes (65 bytes: r=32, s=32, v=1)
        """
        try:
            # Message to sign
            message_text = f"{voter_account.address}{party}{block_number}"
            
            # Use eth_account's signing method
            message = encode_defunct(text=message_text)
            signed_message = voter_account.sign_message(message)
            
            logger.debug(f"Signed vote for {voter_account.address}: {party}")
            return signed_message.signature
        
        except Exception as e:
            logger.error(f"Error signing vote: {e}")
            raise


# ==================== SERIAL PARSING ====================

class SerialParser:
    """
    Parse Arduino Serial output.
    
    FORMAT:
    VOTER_INDEX:X|VOTE:PARTY_Y
    
    Example:
    VOTER_INDEX:0|VOTE:PARTY_A
    VOTER_INDEX:5|VOTE:PARTY_C
    
    WHY THIS CLASS:
    - Encapsulates parsing logic
    - Can validate and sanitize input
    - Can reject malformed strings
    - Easy to unit test
    """
    
    @staticmethod
    def parse(line: str) -> dict or None:
        """
        Parse a serial line into voter_index and party.
        
        Args:
            line: Raw serial string (e.g., "VOTER_INDEX:0|VOTE:PARTY_A")
        
        Returns:
            {'voter_index': int, 'party': str} if valid, None otherwise
        """
        try:
            # Strip whitespace and check format
            line = line.strip()
            if not line:
                logger.warning("Received empty line from Serial")
                return None
            
            # Split by pipe
            if '|' not in line:
                logger.warning(f"Invalid format (no pipe): {line}")
                return None
            
            parts = line.split('|')
            if len(parts) != 2:
                logger.warning(f"Invalid format (expected 2 parts): {line}")
                return None
            
            # Parse VOTER_INDEX:X
            voter_part = parts[0].strip()
            if not voter_part.startswith("VOTER_INDEX:"):
                logger.warning(f"Invalid voter part: {voter_part}")
                return None
            
            voter_index_str = voter_part.replace("VOTER_INDEX:", "").strip()
            try:
                voter_index = int(voter_index_str)
            except ValueError:
                logger.warning(f"Voter index is not an integer: {voter_index_str}")
                return None
            
            if voter_index < 0 or voter_index >= NUM_VOTERS:
                logger.warning(f"Voter index out of range: {voter_index}")
                return None
            
            # Parse VOTE:PARTY_X
            vote_part = parts[1].strip()
            if not vote_part.startswith("VOTE:"):
                logger.warning(f"Invalid vote part: {vote_part}")
                return None
            
            party = vote_part.replace("VOTE:", "").strip()
            if party not in VALID_PARTIES:
                logger.warning(f"Invalid party: {party}")
                return None
            
            logger.info(f"✓ Parsed: voter_{voter_index} voted for {party}")
            return {'voter_index': voter_index, 'party': party}
        
        except Exception as e:
            logger.error(f"Unexpected error parsing serial: {e}")
            return None


# ==================== MAIN ORACLE CLASS ====================

class VotingOracle:
    """
    Main orchestration: Serial → Parse → Sign → Broadcast → Blockchain
    """
    
    def __init__(self):
        """Initialize oracle components."""
        try:
            self.web3_manager = Web3Manager(GANACHE_RPC, CONTRACT_ABI_FILE, CONTRACT_ADDRESS_FILE)
            self.signer = VoteSigner(KEYS_DIR)
            self.serial_conn = None
            
            # Load admin account (for broadcasting transactions)
            admin_key_file = KEYS_DIR / "admin.key"
            with open(admin_key_file, 'r') as f:
                admin_private_key = f.read().strip()
            self.admin_account = Account.from_key(admin_private_key)
            
            logger.info(f"✓ Oracle initialized. Admin: {self.admin_account.address}")
        
        except Exception as e:
            logger.error(f"Error initializing oracle: {e}")
            raise
    
    def connect_serial(self):
        """Connect to Arduino on Serial port."""
        try:
            self.serial_conn = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=5)
            logger.info(f"✓ Connected to {SERIAL_PORT} at {SERIAL_BAUD} baud")
            time.sleep(2)  # Wait for Arduino to initialize
        except Exception as e:
            logger.error(f"Error connecting to {SERIAL_PORT}: {e}")
            raise
    
    def process_vote(self, voter_index: int, party: str) -> bool:
        """
        Process a single vote: load key, sign, broadcast to blockchain.
        
        Args:
            voter_index: 0-9 (from Arduino)
            party: PARTY_A, PARTY_B, PARTY_C, or PARTY_D
        
        Returns:
            True if vote was recorded on-chain, False otherwise
        """
        try:
            # PRE-CHECK: Is poll open?
            if not self.web3_manager.is_poll_open():
                logger.warning(f"Cannot vote: poll is closed. Ignoring voter_{voter_index}")
                return False
            
            # STEP 1: Load voter's private key
            logger.info(f"Processing vote from voter_{voter_index} for {party}")
            voter_account = self.signer.load_voter_key(voter_index)
            
            # STEP 2: Sign the vote
            block_number = self.web3_manager.w3.eth.block_number
            signature = self.signer.sign_vote(voter_account, party, block_number)
            
            # STEP 3: Broadcast to smart contract
            tx_hash = self.web3_manager.submit_vote(
                voter_account.address,
                party,
                signature,
                self.admin_account
            )
            
            return tx_hash is not None
        
        except Exception as e:
            logger.error(f"Error processing vote from voter_{voter_index}: {e}")
            return False
    
    def listen(self):
        """
        Main loop: Listen to Serial, parse, sign, broadcast.
        
        This is where the magic happens:
        - Arduino sends Serial strings
        - Oracle parses and validates
        - Oracle signs with voter's private key
        - Oracle broadcasts to blockchain
        - Blockchain records vote immutably
        """
        logger.info("Oracle listening for votes...")
        logger.info("Waiting for Arduino data...")
        
        vote_count = 0
        error_count = 0
        
        try:
            while True:
                try:
                    # Read line from Serial
                    if self.serial_conn.in_waiting > 0:
                        line = self.serial_conn.readline().decode('utf-8', errors='ignore')
                        
                        # Parse the line
                        parsed = SerialParser.parse(line)
                        if parsed is None:
                            error_count += 1
                            continue
                        
                        # Process the vote
                        success = self.process_vote(parsed['voter_index'], parsed['party'])
                        if success:
                            vote_count += 1
                        else:
                            error_count += 1
                        
                        logger.info(f"Votes recorded: {vote_count}, Errors: {error_count}")
                
                except serial.SerialException as e:
                    logger.error(f"Serial connection error: {e}")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    error_count += 1
        
        except KeyboardInterrupt:
            logger.info("Oracle stopped by user")
        
        finally:
            if self.serial_conn:
                self.serial_conn.close()
            logger.info(f"Final stats - Votes: {vote_count}, Errors: {error_count}")


# ==================== ENTRY POINT ====================

if __name__ == "__main__":
    logger.info("="*70)
    logger.info("BLOCKCHAIN VOTING ORACLE")
    logger.info("="*70)
    
    try:
        oracle = VotingOracle()
        oracle.connect_serial()
        oracle.listen()
    
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)