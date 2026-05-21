// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * VOTING CONTRACT - Blockchain Voting System
 * 
 * Features:
 * - Register exactly 10 voters at deployment
 * - Admin-controlled poll opening/closing
 * - One vote per registered voter (enforced on-chain)
 * - ECDSA signature verification (ecrecover)
 * - Double voting prevention via hasVoted mapping
 * - Event emission for immutable audit trail
 * - Vote count queries
 * 
 * Security:
 * - Only registered voters can vote
 * - Signature must match registered voter address
 * - Once voted, cannot vote again in same poll
 * - All votes recorded as immutable on-chain events
 */

contract VotingContract {
    
    // ==================== STATE VARIABLES ====================
    
    address public admin;
    address[10] public registeredVoters;
    bool public pollOpen;
    
    mapping(address => bool) public hasVoted;
    mapping(bytes32 => uint256) public voteCounts;
    
    // ==================== EVENTS ====================
    
    event VoteRecorded(
        address indexed voter,
        bytes32 indexed party,
        uint256 timestamp,
        uint256 blockNumber
    );
    
    event PollOpened(uint256 timestamp);
    event PollClosed(uint256 timestamp);
    
    // ==================== CONSTRUCTOR ====================
    
    constructor(address[10] memory _registeredVoters) {
        admin = msg.sender;
        registeredVoters = _registeredVoters;
        pollOpen = false;
        
        voteCounts[keccak256("PARTY_A")] = 0;
        voteCounts[keccak256("PARTY_B")] = 0;
        voteCounts[keccak256("PARTY_C")] = 0;
        voteCounts[keccak256("PARTY_D")] = 0;
    }
    
    // ==================== ADMIN FUNCTIONS ====================
    
    function openPoll() public onlyAdmin {
        require(!pollOpen, "Poll is already open");
        pollOpen = true;
        
        for (uint256 i = 0; i < registeredVoters.length; i++) {
            hasVoted[registeredVoters[i]] = false;
        }
        
        emit PollOpened(block.timestamp);
    }
    
    function closePoll() public onlyAdmin {
        require(pollOpen, "Poll is already closed");
        pollOpen = false;
        emit PollClosed(block.timestamp);
    }
    
    function resetVoteCounts() public onlyAdmin {
        require(!pollOpen, "Cannot reset while poll is open");
        
        voteCounts[keccak256("PARTY_A")] = 0;
        voteCounts[keccak256("PARTY_B")] = 0;
        voteCounts[keccak256("PARTY_C")] = 0;
        voteCounts[keccak256("PARTY_D")] = 0;
    }
    
    // ==================== VOTING FUNCTION ====================
    
    function castVote(
        address voter,
        string memory partyName,
        bytes memory signature
    ) public {
        require(pollOpen, "Poll is not open");
        require(isRegisteredVoter(voter), "Voter is not registered");
        require(!hasVoted[voter], "Voter has already voted");
        
        bytes32 messageHash = keccak256(abi.encodePacked(
            voter,
            partyName,
            block.number
        ));
        
        require(
            recoverSigner(messageHash, signature) == voter,
            "Invalid signature"
        );
        
        hasVoted[voter] = true;
        bytes32 partyKey = keccak256(abi.encodePacked(partyName));
        voteCounts[partyKey] += 1;
        
        emit VoteRecorded(
            voter,
            partyKey,
            block.timestamp,
            block.number
        );
    }
    
    // ==================== HELPER FUNCTIONS ====================
    
    function isRegisteredVoter(address _address) public view returns (bool) {
        for (uint256 i = 0; i < registeredVoters.length; i++) {
            if (registeredVoters[i] == _address) {
                return true;
            }
        }
        return false;
    }
    
    function recoverSigner(
        bytes32 messageHash,
        bytes memory signature
    ) internal pure returns (address) {
        require(signature.length == 65, "Invalid signature length");
        
        bytes32 r;
        bytes32 s;
        uint8 v;
        
        assembly {
            r := mload(add(signature, 0x20))
            s := mload(add(signature, 0x40))
            v := byte(0, mload(add(signature, 0x60)))
        }
        
        if (v < 27) {
            v += 27;
        }
        
        return ecrecover(messageHash, v, r, s);
    }
    
    function getVoteCount(string memory partyName) public view returns (uint256) {
        return voteCounts[keccak256(abi.encodePacked(partyName))];
    }
    
    function getAllVoteCounts() public view returns (uint256[4] memory) {
        return [
            voteCounts[keccak256("PARTY_A")],
            voteCounts[keccak256("PARTY_B")],
            voteCounts[keccak256("PARTY_C")],
            voteCounts[keccak256("PARTY_D")]
        ];
    }
    
    function hasVoterVoted(address voter) public view returns (bool) {
        return hasVoted[voter];
    }
    
    // ==================== MODIFIERS ====================
    
    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin can call this");
        _;
    }
}
