"""
simulate_arduino.py - Arduino Serial Simulator

PURPOSE:
- Simulate Arduino Serial output without real hardware
- Send votes in exact format: VOTER_INDEX:X|VOTE:PARTY_Y
- Test oracle.py and smart contract with controlled inputs
- Inject anomalies (malformed strings, duplicates) to test error handling

WHY THIS EXISTS:
- You don't have Arduino hardware on your laptop
- Testing blockchain logic before hardware integration
- Conference demo: show full pipeline (Arduino → Oracle → Blockchain)
- Debugging: easily create specific test cases

HOW IT WORKS:
- Creates a virtual Serial port using pyserial loopback
- Sends vote strings to the loopback
- oracle.py reads from the loopback
- No actual hardware needed

MODES:
1. INTERACTIVE: Send votes manually (type in console)
2. AUTOMATED: Pre-defined test sequence
3. STRESS TEST: Send all 10 voters voting for different parties
4. ANOMALY TEST: Inject malformed strings to test error handling

CONFERENCE TALKING POINT:
"Here's the simulator sending votes. The oracle parses them, signs them with voter
private keys, and broadcasts to the blockchain. You can see each vote recorded as
an immutable event on Ganache. This proves the entire pipeline works."
"""

import serial
import time
import sys
from pathlib import Path

# ==================== CONFIGURATION ====================

# For real Arduino, use actual COM port: "COM3", "COM4", etc.
# For loopback testing on Windows, you can use virtual ports
# See: https://com0com.sourceforge.io/ (free tool for Windows)

# For this demo, we'll use a simple approach: 
# Run this in one terminal, oracle.py in another
# Both read/write to COM3 (or whatever port you configure)

SERIAL_PORT = "COM3"  # Change to match your setup
SERIAL_BAUD = 9600

VALID_PARTIES = {"PARTY_A", "PARTY_B", "PARTY_C", "PARTY_D"}
NUM_VOTERS = 10

# ==================== TEST SEQUENCES ====================

class TestSequences:
    """Pre-defined test cases for different scenarios."""
    
    @staticmethod
    def all_voters_party_a():
        """All 10 voters vote for PARTY_A (boring but good for testing)."""
        votes = []
        for i in range(NUM_VOTERS):
            votes.append(f"VOTER_INDEX:{i}|VOTE:PARTY_A")
        return votes
    
    @staticmethod
    def distributed_votes():
        """Votes distributed across all parties."""
        votes = []
        parties = list(VALID_PARTIES)
        for i in range(NUM_VOTERS):
            party = parties[i % 4]  # Distribute across 4 parties
            votes.append(f"VOTER_INDEX:{i}|VOTE:{party}")
        return votes
    
    @staticmethod
    def stress_test():
        """Each voter votes twice (tests duplicate detection)."""
        votes = []
        for i in range(NUM_VOTERS):
            votes.append(f"VOTER_INDEX:{i}|VOTE:PARTY_A")
        # Send again (duplicates)
        for i in range(NUM_VOTERS):
            votes.append(f"VOTER_INDEX:{i}|VOTE:PARTY_B")
        return votes
    
    @staticmethod
    def anomaly_test():
        """Malformed strings to test error handling."""
        votes = [
            "VOTER_INDEX:0|VOTE:PARTY_A",      # Valid
            "VOTER_INDEX:5|VOTE:INVALID_PARTY",  # Invalid party
            "VOTER_INDEX:99|VOTE:PARTY_A",     # Invalid voter index
            "GARBAGE DATA HERE",                 # No pipe
            "VOTER_INDEX:3",                     # Missing vote part
            "",                                  # Empty line
            "VOTER_INDEX:2|VOTE:PARTY_C",      # Valid
            "VOTER_INDEX:abc|VOTE:PARTY_A",    # Non-integer voter index
        ]
        return votes
    
    @staticmethod
    def mixed_test():
        """Mix of valid votes and anomalies (realistic scenario)."""
        votes = [
            "VOTER_INDEX:0|VOTE:PARTY_A",
            "VOTER_INDEX:1|VOTE:PARTY_B",
            "GARBAGE",  # Anomaly
            "VOTER_INDEX:2|VOTE:PARTY_C",
            "VOTER_INDEX:1|VOTE:PARTY_D",  # Duplicate voter (tests contract)
            "VOTER_INDEX:3|VOTE:PARTY_A",
            "",  # Empty
            "VOTER_INDEX:4|VOTE:PARTY_B",
        ]
        return votes


# ==================== SERIAL SIMULATOR ====================

class ArduinoSimulator:
    """
    Simulate Arduino Serial output.
    
    WHY SEPARATE CLASS:
    - Encapsulates Serial connection
    - Easy to switch between real Arduino and simulator
    - Can be used in other test scripts
    """
    
    def __init__(self, port: str = SERIAL_PORT, baudrate: int = SERIAL_BAUD):
        """
        Initialize Serial connection.
        
        Args:
            port: COM port (e.g., "COM3")
            baudrate: Baud rate (must match Arduino)
        """
        try:
            self.serial_conn = serial.Serial(port, baudrate, timeout=5)
            print(f"✓ Connected to {port} at {baudrate} baud")
            time.sleep(2)  # Wait for connection to stabilize
        except serial.SerialException as e:
            print(f"✗ Error: Cannot connect to {port}")
            print(f"  Details: {e}")
            print(f"\n⚠️  TROUBLESHOOTING:")
            print(f"  1. Check that {port} exists")
            print(f"  2. Ensure Arduino or simulator is running on that port")
            print(f"  3. Make sure oracle.py is NOT already using the port")
            print(f"  4. On Windows, use Device Manager to find Arduino COM port")
            raise
    
    def send_vote(self, voter_index: int, party: str, delay: float = 1.0):
        """
        Send a single vote.
        
        Args:
            voter_index: 0-9
            party: PARTY_A, PARTY_B, PARTY_C, or PARTY_D
            delay: Seconds to wait before sending next vote
        """
        if voter_index < 0 or voter_index >= NUM_VOTERS:
            print(f"✗ Invalid voter index: {voter_index}")
            return False
        
        if party not in VALID_PARTIES:
            print(f"✗ Invalid party: {party}")
            return False
        
        vote_string = f"VOTER_INDEX:{voter_index}|VOTE:{party}\n"
        
        try:
            self.serial_conn.write(vote_string.encode())
            print(f"→ Sent: {vote_string.strip()}")
            time.sleep(delay)
            return True
        except serial.SerialException as e:
            print(f"✗ Serial error: {e}")
            return False
    
    def send_raw(self, raw_string: str, delay: float = 1.0):
        """
        Send raw string (for testing malformed input).
        
        Args:
            raw_string: Arbitrary string
            delay: Seconds to wait
        """
        try:
            self.serial_conn.write((raw_string + "\n").encode())
            print(f"→ Sent: {raw_string}")
            time.sleep(delay)
            return True
        except serial.SerialException as e:
            print(f"✗ Serial error: {e}")
            return False
    
    def send_sequence(self, votes: list, delay: float = 1.0):
        """
        Send a sequence of votes.
        
        Args:
            votes: List of vote strings (e.g., ["VOTER_INDEX:0|VOTE:PARTY_A", ...])
            delay: Delay between votes
        """
        print(f"\n{'='*70}")
        print(f"Sending {len(votes)} votes...")
        print(f"{'='*70}\n")
        
        for i, vote in enumerate(votes, 1):
            print(f"[{i}/{len(votes)}]", end=" ")
            self.send_raw(vote, delay)
        
        print(f"\n✓ Sequence complete\n")
    
    def close(self):
        """Close Serial connection."""
        if self.serial_conn:
            self.serial_conn.close()
            print("Closed Serial connection")


# ==================== INTERACTIVE MODE ====================

def interactive_mode():
    """
    Interactive voting mode: type votes in console.
    
    Useful for manual testing. Type in format:
    VOTER_INDEX:0|VOTE:PARTY_A
    
    Or shorter:
    0 PARTY_A
    """
    print(f"\n{'='*70}")
    print("INTERACTIVE MODE")
    print(f"{'='*70}")
    print("Type votes in format: VOTER_INDEX:X|VOTE:PARTY_Y")
    print("Or shorthand: X PARTY_Y")
    print("Type 'help' for commands")
    print("Type 'exit' to quit\n")
    
    sim = ArduinoSimulator()
    
    try:
        while True:
            user_input = input("Enter vote: ").strip()
            
            if user_input.lower() == "exit":
                break
            elif user_input.lower() == "help":
                print("\nCommands:")
                print("  VOTER_INDEX:0|VOTE:PARTY_A - Send formatted vote")
                print("  0 PARTY_A                   - Send shorthand vote")
                print("  all_a                       - All voters for PARTY_A")
                print("  distributed                 - Distributed votes")
                print("  stress                      - Stress test (duplicates)")
                print("  anomaly                     - Anomaly test")
                print("  mixed                       - Mixed valid + invalid")
                print("  exit                        - Quit\n")
                continue
            elif user_input.lower() == "all_a":
                sim.send_sequence(TestSequences.all_voters_party_a())
                continue
            elif user_input.lower() == "distributed":
                sim.send_sequence(TestSequences.distributed_votes())
                continue
            elif user_input.lower() == "stress":
                sim.send_sequence(TestSequences.stress_test())
                continue
            elif user_input.lower() == "anomaly":
                sim.send_sequence(TestSequences.anomaly_test())
                continue
            elif user_input.lower() == "mixed":
                sim.send_sequence(TestSequences.mixed_test())
                continue
            
            # Parse user input
            if " " in user_input:
                # Shorthand: "0 PARTY_A"
                parts = user_input.split()
                try:
                    voter_idx = int(parts[0])
                    party = parts[1].upper()
                    sim.send_vote(voter_idx, party)
                except (ValueError, IndexError):
                    print("Invalid format. Use: VOTER_INDEX:0|VOTE:PARTY_A")
            else:
                # Full format
                sim.send_raw(user_input)
    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    
    finally:
        sim.close()


# ==================== AUTOMATED MODE ====================

def automated_mode(test_name: str = "distributed"):
    """
    Automated test sequences.
    
    Args:
        test_name: "all_a", "distributed", "stress", "anomaly", "mixed"
    """
    print(f"\n{'='*70}")
    print(f"AUTOMATED MODE: {test_name}")
    print(f"{'='*70}\n")
    
    # Select test sequence
    sequences = {
        "all_a": TestSequences.all_voters_party_a,
        "distributed": TestSequences.distributed_votes,
        "stress": TestSequences.stress_test,
        "anomaly": TestSequences.anomaly_test,
        "mixed": TestSequences.mixed_test,
    }
    
    if test_name not in sequences:
        print(f"Unknown test: {test_name}")
        print(f"Available: {', '.join(sequences.keys())}")
        return
    
    test_func = sequences[test_name]
    votes = test_func()
    
    sim = ArduinoSimulator()
    
    try:
        sim.send_sequence(votes, delay=0.5)
        print(f"✓ {test_name} test complete")
    except KeyboardInterrupt:
        print("Test interrupted by user")
    finally:
        sim.close()


# ==================== ENTRY POINT ====================

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print("ARDUINO SIMULATOR FOR BLOCKCHAIN VOTING SYSTEM")
    print(f"{'='*70}\n")
    
    # Parse command line arguments
    mode = "interactive"
    test_name = "distributed"
    
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
    
    if len(sys.argv) > 2:
        test_name = sys.argv[2].lower()
    
    try:
        if mode == "interactive" or mode == "-i":
            interactive_mode()
        
        elif mode == "automated" or mode == "-a":
            automated_mode(test_name)
        
        elif mode == "help" or mode == "-h":
            print("USAGE:")
            print("  python simulate_arduino.py              # Interactive mode (default)")
            print("  python simulate_arduino.py -i           # Interactive mode")
            print("  python simulate_arduino.py -a all_a     # Automated: all voters for PARTY_A")
            print("  python simulate_arduino.py -a distributed # Automated: distributed votes")
            print("  python simulate_arduino.py -a stress    # Automated: stress test (duplicates)")
            print("  python simulate_arduino.py -a anomaly   # Automated: malformed strings")
            print("  python simulate_arduino.py -a mixed     # Automated: mix of valid + invalid\n")
            print("INTERACTIVE COMMANDS:")
            print("  VOTER_INDEX:0|VOTE:PARTY_A - Send formatted vote")
            print("  0 PARTY_A                   - Send shorthand vote")
            print("  all_a, distributed, stress, anomaly, mixed - Run test sequences")
            print("  help - Show this message")
            print("  exit - Quit\n")
        
        else:
            print(f"Unknown mode: {mode}")
            print("Use: python simulate_arduino.py -h for help\n")
    
    except KeyboardInterrupt:
        print("\nSimulator stopped by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        exit(1)