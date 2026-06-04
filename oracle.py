import os
import sys
import serial
import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

# ==================== CONFIGURATION ====================

SERIAL_PORT = "COM12"
SERIAL_BAUD = 9600

GANACHE_RPC = "http://127.0.0.1:7545"

KEYS_DIR = Path("keys")
CONTRACT_ABI_FILE = "VotingContract.json"
CONTRACT_ADDRESS_FILE = "contract_address.txt"

VALID_PARTIES = {"PARTY_A", "PARTY_B", "PARTY_C", "PARTY_D"}
NUM_VOTERS = 10

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("voting_oracle.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ==================== WEB3 SETUP ====================

class Web3Manager:
    def __init__(self, rpc_url: str, contract_abi_file: str, contract_address_file: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))

        if not self.w3.is_connected():
            raise RuntimeError(f"Cannot connect to {rpc_url}. Is Ganache running?")

        logger.info(f"Connected to Ganache at {rpc_url}")
        logger.info(f"Block number: {self.w3.eth.block_number}")

        with open(contract_abi_file, 'r') as f:
            contract_data = json.load(f)
            self.contract_abi = contract_data.get("abi") or contract_data

        with open(contract_address_file, 'r') as f:
            self.contract_address = f.read().strip()

        self.contract = self.w3.eth.contract(
            address=self.contract_address,
            abi=self.contract_abi
        )

        logger.info(f"Loaded VotingContract at {self.contract_address}")

    def is_poll_open(self) -> bool:
        try:
            return self.contract.functions.pollOpen().call()
        except Exception as e:
            logger.error(f"Error checking poll state: {e}")
            return False

    def submit_vote(self, voter_address: str, party: str, signature: bytes, admin_account) -> str:
        try:
            tx = self.contract.functions.castVote(
                voter_address,
                party,
                signature
            ).build_transaction({
                'from': admin_account.address,
                'nonce': self.w3.eth.get_transaction_count(admin_account.address),
                'gas': 300000,
                'gasPrice': self.w3.eth.gas_price,
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, admin_account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

            if receipt.status == 1:
                logger.info(f"Vote recorded. Tx: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Transaction failed. Tx: {tx_hash.hex()}")
                return None

        except Exception as e:
            logger.error(f"Error submitting vote to contract: {e}")
            return None


# ==================== SIGNING LOGIC ====================

class VoteSigner:
    def __init__(self, keys_dir: Path, w3: Web3):
        self.keys_dir = keys_dir
        self.w3 = w3
        self._key_cache = {}

    def load_voter_key(self, voter_index: int) -> Account:
        if voter_index in self._key_cache:
            return self._key_cache[voter_index]

        # Arduino sends 0-9, keys are voter_0.key to voter_9.key
        key_file = self.keys_dir / f"voter_{voter_index}.key"

        if not key_file.exists():
            raise FileNotFoundError(f"Key file not found: {key_file}")

        with open(key_file, 'r') as f:
            private_key_hex = f.read().strip()

        account = Account.from_key(private_key_hex)
        self._key_cache[voter_index] = account
        logger.debug(f"Loaded Voter {voter_index + 1} key: {account.address}")
        return account

    def sign_vote(self, voter_account: Account, party: str) -> bytes:
        try:
            raw_hash = self.w3.solidity_keccak(
                ['address', 'string'],
                [voter_account.address, party]
            )
            message = encode_defunct(primitive=raw_hash)
            signed_message = voter_account.sign_message(message)
            logger.debug(f"Signed vote for {voter_account.address}: {party}")
            return signed_message.signature

        except Exception as e:
            logger.error(f"Error signing vote: {e}")
            raise


# ==================== SERIAL PARSING ====================

class SerialParser:
    @staticmethod
    def parse(line: str):
        try:
            line = line.strip()
            if not line:
                logger.warning("Received empty line from Serial")
                return None

            if '|' not in line:
                logger.warning(f"Invalid format (no pipe): {line}")
                return None

            parts = line.split('|')
            if len(parts) != 2:
                logger.warning(f"Invalid format (expected 2 parts): {line}")
                return None

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

            # Arduino sends 0-9
            if voter_index < 0 or voter_index >= NUM_VOTERS:
                logger.warning(f"Voter index out of range: {voter_index}")
                return None

            vote_part = parts[1].strip()
            if not vote_part.startswith("VOTE:"):
                logger.warning(f"Invalid vote part: {vote_part}")
                return None

            party = vote_part.replace("VOTE:", "").strip()
            if party not in VALID_PARTIES:
                logger.warning(f"Invalid party: {party}")
                return None

            # Display as 1-10 in logs
            logger.info(f"Parsed: Voter {voter_index + 1} voted for {party}")
            return {'voter_index': voter_index, 'party': party}

        except Exception as e:
            logger.error(f"Unexpected error parsing serial: {e}")
            return None


# ==================== MAIN ORACLE CLASS ====================

class VotingOracle:
    def __init__(self):
        try:
            self.web3_manager = Web3Manager(GANACHE_RPC, CONTRACT_ABI_FILE, CONTRACT_ADDRESS_FILE)
            self.signer = VoteSigner(KEYS_DIR, self.web3_manager.w3)
            self.serial_conn = None

            admin_private_key = os.getenv("GANACHE_ADMIN_PRIVATE_KEY")
            self.admin_account = Account.from_key(admin_private_key)

            logger.info(f"Oracle initialized. Admin: {self.admin_account.address}")

        except Exception as e:
            logger.error(f"Error initializing oracle: {e}")
            raise

    def connect_serial(self):
        try:
            self.serial_conn = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=5)
            logger.info(f"Connected to {SERIAL_PORT} at {SERIAL_BAUD} baud")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Error connecting to {SERIAL_PORT}: {e}")
            raise

    def process_vote(self, voter_index: int, party: str) -> bool:
        try:
            if not self.web3_manager.is_poll_open():
                logger.warning(f"Cannot vote: poll is closed. Ignoring Voter {voter_index + 1}")
                return False

            logger.info(f"Processing vote from Voter {voter_index + 1} for {party}")
            voter_account = self.signer.load_voter_key(voter_index)
            signature = self.signer.sign_vote(voter_account, party)

            tx_hash = self.web3_manager.submit_vote(
                voter_account.address,
                party,
                signature,
                self.admin_account
            )

            if tx_hash:
                logger.info(f"Voter {voter_index + 1} vote confirmed on blockchain")

            return tx_hash is not None

        except Exception as e:
            logger.error(f"Error processing vote from Voter {voter_index + 1}: {e}")
            return False

    def listen(self):
        logger.info("Oracle listening for votes...")
        logger.info("Waiting for Arduino data...")

        vote_count = 0
        error_count = 0

        try:
            while True:
                try:
                    if self.serial_conn.in_waiting > 0:
                        line = self.serial_conn.readline().decode('utf-8', errors='ignore')

                        parsed = SerialParser.parse(line)
                        if parsed is None:
                            error_count += 1
                            continue

                        success = self.process_vote(parsed['voter_index'], parsed['party'])
                        if success:
                            vote_count += 1
                        else:
                            error_count += 1

                        logger.info(f"Total votes on blockchain: {vote_count} | Errors: {error_count}")

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