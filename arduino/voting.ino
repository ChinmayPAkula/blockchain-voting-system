/*
 * MPMC PROJECT: SECURE BLOCKCHAIN VOTING SYSTEM
 * WIRING:
 * - LCD (I2C): A4 (SDA), A5 (SCL)
 * - RFID (SPI): D9 (RST), D10 (SS), D11 (MOSI), D12 (MISO), D13 (SCK)
 * - LEDs: A0 (Red), A1 (Green), A2 (Blue), A3 (Yellow)
 * - Buttons: D2, D3, D4, D5
 * - Buzzer: D6
 */

#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <EEPROM.h>

// --- 1. PIN DEFINITIONS ---
#define RST_PIN    9
#define SS_PIN     10
#define BTN_A      2
#define BTN_B      3
#define BTN_C      4
#define BTN_D      5
#define LED_RED    A0
#define LED_GREEN  A1
#define LED_BLUE   A2
#define LED_YELLOW A3
#define BUZZER     6

// --- 2. OBJECT INITIALIZATION ---
LiquidCrystal_I2C lcd(0x27, 16, 2); 
MFRC522 rfid(SS_PIN, RST_PIN);

// --- 3. VOTER DATA ---
byte adminUID[4] = {0xA3, 0x13, 0x01, 0x1D};
const int numVoters = 10;
byte voterUIDs[numVoters][4] = {
  {0x7D, 0x37, 0xD5, 0x3C}, // Voter 1
  {0x84, 0xD8, 0x1B, 0xA9}, // Voter 2
  {0x87, 0x32, 0x18, 0x06}, // Voter 3
  {0xB3, 0xB9, 0x25, 0x1D}, // Voter 4
  {0xBB, 0xC8, 0x0C, 0x1A}, // Voter 5
  {0x8B, 0xC3, 0x09, 0x1A}, // Voter 6
  {0x5D, 0x68, 0xFB, 0x6B}, // Voter 7
  {0xED, 0xF3, 0xDE, 0x6B}, // Voter 8
  {0xAD, 0xE6, 0xE6, 0x6B}, // Voter 9
  {0xB4, 0x7A, 0x46, 0xFE}  // Voter 10
};

// --- 4. GLOBAL STATE ---
int votesA = 0, votesB = 0, votesC = 0, votesD = 0;
bool hasVoted[numVoters] = {false}; 
bool pollsOpen = false;

// --- 5. SETUP ---
void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();
  Wire.begin();
  lcd.init();
  lcd.backlight();

  pinMode(BTN_A, INPUT_PULLUP);
  pinMode(BTN_B, INPUT_PULLUP);
  pinMode(BTN_C, INPUT_PULLUP);
  pinMode(BTN_D, INPUT_PULLUP);
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(BUZZER, OUTPUT);

  // Restore State from EEPROM
  for (int i = 0; i < numVoters; i++) {
    if (EEPROM.read(i) == 1) {
      hasVoted[i] = true;
    } else {
      hasVoted[i] = false;
    }
  }

  setLEDs(true, false, false, false); // RED ON
  lcd.setCursor(0, 0);
  lcd.print("POLLS CLOSED.");
  lcd.setCursor(0, 1);
  lcd.print("Scan Admin Card");
}

// --- 6. MAIN LOOP ---
void loop() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    delay(50); 
    return;    
  }

  if (checkUID(rfid.uid.uidByte, adminUID)) {
    handleAdminCard();
  }
  else if (pollsOpen) {
    handleVoterCard(rfid.uid.uidByte);
  }
  else {
    showError("Error: Polls Not", "Open!", 1500);
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

// --- 7. ADMIN FUNCTIONS ---
void handleAdminCard() {
  // SECRET WIPE COMBO: Hold Button D while tapping Admin
  if (digitalRead(BTN_D) == LOW) {
    lcd.clear();
    lcd.print("WIPING MEMORY...");
    lcd.setCursor(0, 1);
    lcd.print("Please Wait.");
    playTone(400, 500);
    
    for (int i = 0; i < numVoters; i++) {
      EEPROM.write(i, 0);
      hasVoted[i] = false;
    }
    votesA = 0; votesB = 0; votesC = 0; votesD = 0;
    
    delay(1500);
    lcd.clear();
    lcd.print("MEMORY CLEARED");
    lcd.setCursor(0, 1);
    lcd.print("Ready!!");
    delay(2000);
    
    lcd.clear();
    lcd.print("POLLS CLOSED.");
    lcd.setCursor(0, 1);
    lcd.print("Scan Admin Card");
    return; 
  }

  if (pollsOpen) {
    pollsOpen = false;
    setLEDs(true, false, false, false);
    playTone(1200, 300);
    lcd.clear();
    lcd.print("POLLS CLOSED.");
    lcd.setCursor(0, 1);
    lcd.print("Tallying...");
    delay(2000);
    displayResults();
    while (true) {} // System freeze on results
  } else {
    pollsOpen = true;
    setLEDs(false, true, false, false);
    playTone(800, 150);
    lcd.clear();
    lcd.print("POLLS OPEN!");
    lcd.setCursor(0, 1);
    lcd.print("Scan Voter ID");
  }
}

// --- 8. VOTER FUNCTIONS ---
void handleVoterCard(byte* scannedUID) {
  int voterIndex = getVoterIndex(scannedUID);

  if (voterIndex != -1) {
    if (hasVoted[voterIndex]) {

      Serial.print("HARDWARE_ANOMALY:VOTER_INDEX:");
      Serial.print(voterIndex);
      Serial.println("|REASON:ALREADY_VOTED_EEPROM");
      
      showError("Card Already Used", "Vote Rejected.", 2000);
      setLEDs(false, true, false, false); 
    } else {
      setLEDs(false, false, true, false); 
      playTone(1000, 200);
      lcd.clear();
      lcd.print("Voter Accepted!");
      lcd.setCursor(0, 1);
      lcd.print("Please Vote...");
      waitForVote(voterIndex);
    }
  } else {
    showError("Invalid Voter ID", "Access Denied.", 2000);
    setLEDs(false, true, false, false);
  }
}

void waitForVote(int voterIndex) {
  // SAFETY FLUSH: Wait for finger to be lifted from all buttons
  while(digitalRead(BTN_A) == LOW || digitalRead(BTN_B) == LOW || 
        digitalRead(BTN_C) == LOW || digitalRead(BTN_D) == LOW) { delay(10); }

  bool voteCasted = false;
  while (!voteCasted) {
    if (digitalRead(BTN_A) == LOW) {
      votesA++;
      sendSerialData(voterIndex, "PARTY_A");
      showVoteConfirmation("Vote for Party A", "Cast! Thank you.");
      voteCasted = true;
    } else if (digitalRead(BTN_B) == LOW) {
      votesB++;
      sendSerialData(voterIndex, "PARTY_B");
      showVoteConfirmation("Vote for Party B", "Cast! Thank you.");
      voteCasted = true;
    } else if (digitalRead(BTN_C) == LOW) {
      votesC++;
      sendSerialData(voterIndex, "PARTY_C");
      showVoteConfirmation("Vote for Party C", "Cast! Thank you.");
      voteCasted = true;
    } else if (digitalRead(BTN_D) == LOW) {
      votesD++;
      sendSerialData(voterIndex, "PARTY_D");
      showVoteConfirmation("Vote for Party D", "Cast! Thank you.");
      voteCasted = true;
    }
  }
  
  hasVoted[voterIndex] = true; 
  EEPROM.write(voterIndex, 1);
  delay(2000);
  setLEDs(false, true, false, false);
  lcd.clear();
  lcd.print("POLLS OPEN!");
  lcd.setCursor(0, 1);
  lcd.print("Scan Voter ID");
}

void sendSerialData(int index, String party) {
  Serial.print("VOTER_INDEX:");
  Serial.print(index);
  Serial.print("|VOTE:");
  Serial.println(party);
}

// --- 9. HELPER FUNCTIONS ---
void displayResults() {
  lcd.clear();
  lcd.print("A:" + String(votesA) + " B:" + String(votesB));
  lcd.setCursor(0, 1);
  lcd.print("C:" + String(votesC) + " D:" + String(votesD));
  delay(4000);

  int maxVotes = max(max(votesA, votesB), max(votesC, votesD));
  lcd.clear();
  if (maxVotes == 0) lcd.print("No votes cast!");
  else if ((votesA == maxVotes) + (votesB == maxVotes) + (votesC == maxVotes) + (votesD == maxVotes) > 1) lcd.print("Result: TIE!");
  else if (votesA == maxVotes) lcd.print("Party A Wins!");
  else if (votesB == maxVotes) lcd.print("Party B Wins!");
  else if (votesC == maxVotes) lcd.print("Party C Wins!");
  else if (votesD == maxVotes) lcd.print("Party D Wins!");
}

void showError(String line1, String line2, int delayMs) {
  lcd.clear();
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
  playTone(300, 500);
  for(int i=0; i<3; i++){
    digitalWrite(LED_RED, HIGH); delay(100);
    digitalWrite(LED_RED, LOW); delay(100);
  }
  delay(delayMs - 600);
}

void showVoteConfirmation(String line1, String line2) {
  lcd.clear();
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
  playTone(1200, 100);
  digitalWrite(LED_YELLOW, HIGH); delay(200);
  digitalWrite(LED_YELLOW, LOW);
}

void setLEDs(bool r, bool g, bool b, bool y) {
  digitalWrite(LED_RED, r);
  digitalWrite(LED_GREEN, g);
  digitalWrite(LED_BLUE, b);
  digitalWrite(LED_YELLOW, y);
}

void playTone(int frequency, int duration) {
  tone(BUZZER, frequency, duration);
}

bool checkUID(byte* uid1, byte* uid2) {
  for (int i = 0; i < 4; i++) {
    if (uid1[i] != uid2[i]) return false;
  }
  return true;
}

int getVoterIndex(byte* uid) {
  for (int i = 0; i < numVoters; i++) {
    if (checkUID(uid, voterUIDs[i])) return i;
  }
  return -1;
}