/*
  Ojos de robot - ESP32-S3 + OLED SSD1306 + Micrófono INMP441 (I2S)
  ---------------------------------------------------------------
  ETAPA 4: Integración micrófono + OLED con VAD simple (umbral RMS)

  Conexiones ESP32-S3-N8R2:
    OLED (I2C):  SDA -> GPIO8,  SCL -> GPIO9
    INMP441 (I2S): WS -> GPIO4, SCK -> GPIO5, SD -> GPIO6, VDD -> 3V3, GND -> GND, L/R -> GND

  Librerías necesarias:
    - Adafruit GFX
    - Adafruit SSD1306

  Comportamiento:
    - Micrófono lee I2S continuamente y calcula RMS (nivel de audio)
    - RMS > UMBRAL_VOZ  -> setExpression(STATE_LISTENING)  (ojos con anillo pulsante)
    - RMS < UMBRAL_SILENCIO por TIEMPO_SILENCIO_MS -> setExpression(STATE_IDLE)
    - Serial sigue aceptando comandos en inglés (idle, happy, thinking, etc.) para prueba manual
*/

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <driver/i2s.h>

// ============================================================
//  CONFIGURACIÓN HARDWARE (ESP32-S3-N8R2)
// ============================================================
// OLED I2C
#define OLED_SDA       8
#define OLED_SCL       9
#define SCREEN_WIDTH   128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1
#define SCREEN_ADDRESS 0x3C

// INMP441 I2S
#define I2S_PORT       I2S_NUM_0
#define I2S_WS         4
#define I2S_SCK        5
#define I2S_SD         6
#define SAMPLE_RATE    16000
#define I2S_BUFFER_MS  20              // Ventana de análisis (ms)
#define I2S_READ_LEN   (SAMPLE_RATE * I2S_BUFFER_MS / 1000)  // 320 samples @ 16kHz / 20ms

// ============================================================
//  CONFIGURACIÓN VAD (Voice Activity Detection) SIMPLE
// ============================================================
// Ajustá estos valores tras probar el monitor serie (ver barras #)
#define RMS_THRESHOLD_SPEAK     60000    // Entrar en LISTENING (bien arriba del silencio)
#define RMS_THRESHOLD_SILENCE  35000   // Volver a IDLE (arriba del silencio, abajo del speak)
#define SILENCE_HOLD_MS        2000    // Cuánto silencio sostenido antes de volver a IDLE
#define VAD_PRINT_INTERVAL_MS  100     // Cada cuánto imprimir barra RMS en Serial (0 = no imprimir)

// ============================================================
//  OBJETOS GLOBALES
// ============================================================
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// Buffer I2S (32-bit samples del INMP441, aunque solo usamos 24 bits útiles)
static int32_t i2s_read_buffer[I2S_READ_LEN];

// ============================================================
//  1. ESTADOS DEL AGENTE (igual que robot_eyes2_estados.ino)
// ============================================================
enum AgentState {
  STATE_IDLE = 0,
  STATE_HAPPY,
  STATE_THINKING,
  STATE_SURPRISED,
  STATE_SLEEPY,
  STATE_CONFUSED,
  STATE_ANGRY,
  STATE_LISTENING,
  STATE_SPEAKING,
  STATE_COUNT
};

AgentState currentState = STATE_IDLE;

struct StateConfig {
  AgentState state;
  const char* name;
  int weight;
  unsigned long minDuration;
  unsigned long maxDuration;
};

StateConfig autonomousPool[] = {
  { STATE_IDLE,       "IDLE",       45, 4000, 9000 },
  { STATE_HAPPY,      "HAPPY",      20, 2500, 4500 },
  { STATE_THINKING,   "THINKING",   15, 3000, 6000 },
  { STATE_SLEEPY,     "SLEEPY",     10, 3000, 6000 },
  { STATE_SURPRISED,  "SURPRISED",   4,  900, 1600 },
  { STATE_CONFUSED,   "CONFUSED",    4, 2000, 3500 },
  { STATE_ANGRY,      "ANGRY",       2, 1500, 2500 },
};
const int autonomousPoolSize = sizeof(autonomousPool) / sizeof(autonomousPool[0]);

// ============================================================
//  2. TEMPORIZADORES / ESTADO INTERNO
// ============================================================
unsigned long stateStartTime = 0;
unsigned long currentStateDuration = 4000;
unsigned long lastIdleBlinkTime = 0;
const unsigned long idleBlinkInterval = 3000;
bool isTransitioning = false;

// VAD state
unsigned long lastVoiceTime = 0;
unsigned long lastVadPrintTime = 0;
bool vadActive = false;  // true = estamos en LISTENING por voz detectada

// ============================================================
//  DECLARACIONES ADELANTADAS
// ============================================================
void setExpression(AgentState newState, bool withTransition = true);
void renderExpression(AgentState state);
void chooseNextAutonomousState();
void playTransitionBlink();
void checkSerialCommand();
void initI2SMic();
int computeRMS(int32_t* buffer, int len);
void updateVAD(int rms);
void drawIdle(); void drawHappy(); void drawThinking(); void drawSurprised();
void drawSleepy(); void drawConfused(); void drawAngry(); void drawListening(); void drawSpeaking();
void drawThickArc(int cx, int cy, int r, float startDeg, float endDeg, int thickness);
void drawLidsHeight(int currentHeight);
void quickBlinkOnly();

// Geometría ojos
int eyeWidth = 40, eyeHeight = 40, eyeRadius = 10, eyeSpacing = 20;
int leftEyeX, rightEyeX, eyeY;
int leftEyeCX, rightEyeCX, eyeCY;

// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(500);  // Dar tiempo a abrir monitor serie

  // --- I2C OLED ---
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(400000);

  if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
    Serial.println(F("Error: no se detectó la pantalla OLED"));
    while (true);
  }

  int totalWidth = (eyeWidth * 2) + eyeSpacing;
  leftEyeX  = (SCREEN_WIDTH - totalWidth) / 2;
  rightEyeX = leftEyeX + eyeWidth + eyeSpacing;
  eyeY = (SCREEN_HEIGHT - eyeHeight) / 2;
  leftEyeCX  = leftEyeX + eyeWidth / 2;
  rightEyeCX = rightEyeX + eyeWidth / 2;
  eyeCY = eyeY + eyeHeight / 2;

  // --- I2S Micrófono ---
  initI2SMic();

  randomSeed(esp_random());

  display.clearDisplay();
  currentState = STATE_IDLE;
  stateStartTime = millis();
  currentStateDuration = random(4000, 9000);
  renderExpression(currentState);

  Serial.println(F("=== Agente con VAD listo ==="));
  Serial.println(F("Estados por Serial: idle, happy, thinking, surprised, sleepy, confused, angry, listening, speaking"));
  Serial.println(F("VAD: habla cerca del mic -> LISTENING; silencio -> IDLE"));
  Serial.print(F("Umbrales: speak=")); Serial.print(RMS_THRESHOLD_SPEAK);
  Serial.print(F(" silence=")); Serial.println(RMS_THRESHOLD_SILENCE);
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
  updateAgent();
  checkSerialCommand();
  updateMicrophone();
}

// ============================================================
//  3. updateAgent(): reloj de expresiones (sin cambios lógicos)
// ============================================================
void updateAgent() {
  unsigned long now = millis();

  // Micro-parpadeo solo en IDLE
  if (currentState == STATE_IDLE && !isTransitioning) {
    if (now - lastIdleBlinkTime >= idleBlinkInterval) {
      quickBlinkOnly();
      lastIdleBlinkTime = now;
    }
  }

  // Animaciones continuas (thinking, listening, speaking)
  if (!isTransitioning) {
    renderExpression(currentState);
  }

  // Auto-cambio solo para estados autónomos (no LISTENING/SPEAKING forzados)
  bool isAutonomousState = (currentState != STATE_LISTENING && currentState != STATE_SPEAKING);
  if (isAutonomousState && (now - stateStartTime >= currentStateDuration)) {
    chooseNextAutonomousState();
  }
}

// ============================================================
//  4. Selección aleatoria autónoma (sin cambios)
// ============================================================
void chooseNextAutonomousState() {
  int totalWeight = 0;
  for (int i = 0; i < autonomousPoolSize; i++) {
    if (autonomousPool[i].state == currentState) continue;
    totalWeight += autonomousPool[i].weight;
  }

  int pick = random(0, totalWeight);
  int cumulative = 0;
  StateConfig chosen = autonomousPool[0];

  for (int i = 0; i < autonomousPoolSize; i++) {
    if (autonomousPool[i].state == currentState) continue;
    cumulative += autonomousPool[i].weight;
    if (pick < cumulative) {
      chosen = autonomousPool[i];
      break;
    }
  }

  currentStateDuration = random(chosen.minDuration, chosen.maxDuration);
  setExpression(chosen.state);

  Serial.print(F("[auto] nuevo estado: "));
  Serial.print(chosen.name);
  Serial.print(F(" durante "));
  Serial.print(currentStateDuration);
  Serial.println(F(" ms"));
}

// ============================================================
//  5. setExpression(): punto único de entrada (sin cambios)
// ============================================================
void setExpression(AgentState newState, bool withTransition) {
  if (withTransition) {
    playTransitionBlink();
  }
  currentState = newState;
  stateStartTime = millis();
  renderExpression(currentState);

  // Si el VAD nos puso en LISTENING y ahora forzamos otro estado por Serial,
  // desactivamos el VAD para que no vuelva a IDLE solo
  if (newState != STATE_LISTENING && newState != STATE_SPEAKING) {
    vadActive = false;
  }
}

// ============================================================
//  6. Transición: parpadeo genérico (sin cambios)
// ============================================================
void playTransitionBlink() {
  isTransitioning = true;
  const int steps = 5;
  int stepSize = eyeHeight / steps;
  int stepDelay = 20;

  for (int h = eyeHeight; h >= 2; h -= stepSize) {
    drawLidsHeight(h);
    delay(stepDelay);
  }
  delay(60);
  isTransitioning = false;
}

void drawLidsHeight(int currentHeight) {
  display.clearDisplay();
  int yOffset = eyeY + (eyeHeight - currentHeight) / 2;
  int radius = min(eyeRadius, currentHeight / 2);
  if (radius < 1) radius = 1;
  display.fillRoundRect(leftEyeX, yOffset, eyeWidth, currentHeight, radius, SSD1306_WHITE);
  display.fillRoundRect(rightEyeX, yOffset, eyeWidth, currentHeight, radius, SSD1306_WHITE);
  display.display();
}

void quickBlinkOnly() {
  isTransitioning = true;
  const int steps = 5;
  int stepSize = eyeHeight / steps;
  int stepDelay = 16;
  for (int h = eyeHeight; h >= 2; h -= stepSize) { drawLidsHeight(h); delay(stepDelay); }
  delay(40);
  for (int h = 2; h <= eyeHeight; h += stepSize) { drawLidsHeight(h); delay(stepDelay); }
  drawLidsHeight(eyeHeight);
  isTransitioning = false;
}

// ============================================================
//  7. Dispatcher de expresiones (sin cambios)
// ============================================================
void renderExpression(AgentState state) {
  switch (state) {
    case STATE_IDLE:       drawIdle();       break;
    case STATE_HAPPY:      drawHappy();      break;
    case STATE_THINKING:   drawThinking();   break;
    case STATE_SURPRISED:  drawSurprised();  break;
    case STATE_SLEEPY:     drawSleepy();     break;
    case STATE_CONFUSED:   drawConfused();   break;
    case STATE_ANGRY:      drawAngry();      break;
    case STATE_LISTENING:  drawListening();  break;
    case STATE_SPEAKING:   drawSpeaking();   break;
    default:               drawIdle();       break;
  }
}

// ============================================================
//  8. Helper: arco grueso (sin cambios)
// ============================================================
void drawThickArc(int cx, int cy, int r, float startDeg, float endDeg, int thickness) {
  const int samples = 14;
  for (int i = 0; i <= samples; i++) {
    float t = startDeg + (endDeg - startDeg) * ((float)i / samples);
    float rad = t * PI / 180.0;
    int x = cx + (int)(cos(rad) * r);
    int y = cy + (int)(sin(rad) * r);
    display.fillCircle(x, y, thickness, SSD1306_WHITE);
  }
}

// ============================================================
//  9. EXPRESIONES (sin cambios lógicos, solo copiadas)
// ============================================================
void drawIdle() {
  display.clearDisplay();
  int radius = eyeRadius;
  display.fillRoundRect(leftEyeX, eyeY, eyeWidth, eyeHeight, radius, SSD1306_WHITE);
  display.fillRoundRect(rightEyeX, eyeY, eyeWidth, eyeHeight, radius, SSD1306_WHITE);
  display.display();
}

void drawHappy() {
  display.clearDisplay();
  int r = eyeWidth / 2;
  int thickness = 4;
  drawThickArc(leftEyeCX,  eyeCY + r / 2, r, 200, 340, thickness);
  drawThickArc(rightEyeCX, eyeCY + r / 2, r, 200, 340, thickness);
  display.display();
}

void drawSleepy() {
  display.clearDisplay();
  int r = eyeWidth / 2;
  int thickness = 3;
  drawThickArc(leftEyeCX,  eyeCY - r / 2, r, 20, 160, thickness);
  drawThickArc(rightEyeCX, eyeCY - r / 2, r, 20, 160, thickness);
  display.display();
}

void drawSurprised() {
  display.clearDisplay();
  int r = (eyeWidth / 2) + 4;
  display.fillCircle(leftEyeCX, eyeCY, r, SSD1306_WHITE);
  display.fillCircle(rightEyeCX, eyeCY, r, SSD1306_WHITE);
  display.display();
}

void drawThinking() {
  display.clearDisplay();
  int thinHeight = eyeHeight / 3;
  int yOffset = eyeY + (eyeHeight - thinHeight) / 2;
  int radius = min(eyeRadius, thinHeight / 2);
  if (radius < 1) radius = 1;
  display.fillRoundRect(leftEyeX, yOffset, eyeWidth, thinHeight, radius, SSD1306_WHITE);
  display.fillRoundRect(rightEyeX, yOffset, eyeWidth, thinHeight, radius, SSD1306_WHITE);
  int dotsY = eyeY + eyeHeight + 10;
  int dotsCenterX = SCREEN_WIDTH / 2;
  int spacing = 10;
  int activeDot = (millis() / 300) % 3;
  for (int i = -1; i <= 1; i++) {
    int dx = dotsCenterX + i * spacing;
    int radius2 = (i + 1 == activeDot) ? 3 : 1;
    display.fillCircle(dx, dotsY, radius2, SSD1306_WHITE);
  }
  display.display();
}

void drawConfused() {
  display.clearDisplay();
  int r = eyeWidth / 2;
  display.fillCircle(leftEyeCX, eyeCY, r - 2, SSD1306_WHITE);
  display.fillCircle(rightEyeCX, eyeCY + 3, r - 6, SSD1306_WHITE);
  display.drawLine(rightEyeCX - r + 2, eyeCY - r - 2, rightEyeCX + r - 6, eyeCY - r + 6, SSD1306_WHITE);
  display.drawLine(rightEyeCX - r + 2, eyeCY - r - 1, rightEyeCX + r - 6, eyeCY - r + 7, SSD1306_WHITE);
  display.display();
}

void drawAngry() {
  display.clearDisplay();
  int h = eyeHeight / 2;
  int yTop = eyeCY - h / 2;
  int yBot = eyeCY + h / 2;
  display.fillTriangle(leftEyeX, yTop, leftEyeX + eyeWidth, yBot, leftEyeX, yBot, SSD1306_WHITE);
  display.fillTriangle(leftEyeX, yTop, leftEyeX + eyeWidth, yTop + h / 2, leftEyeX + eyeWidth, yBot, SSD1306_WHITE);
  display.fillTriangle(rightEyeX + eyeWidth, yTop, rightEyeX, yBot, rightEyeX + eyeWidth, yBot, SSD1306_WHITE);
  display.fillTriangle(rightEyeX + eyeWidth, yTop, rightEyeX, yTop + h / 2, rightEyeX, yBot, SSD1306_WHITE);
  display.display();
}

void drawListening() {
  display.clearDisplay();
  int r = eyeWidth / 2 - 2;
  display.fillCircle(leftEyeCX, eyeCY, r, SSD1306_WHITE);
  display.fillCircle(rightEyeCX, eyeCY, r, SSD1306_WHITE);
  float phase = (millis() % 1000) / 1000.0;
  int pulseR = r + 4 + (int)(6 * sin(phase * 2 * PI));
  display.drawCircle(leftEyeCX, eyeCY, pulseR, SSD1306_WHITE);
  display.drawCircle(rightEyeCX, eyeCY, pulseR, SSD1306_WHITE);
  display.display();
}

void drawSpeaking() {
  display.clearDisplay();
  float phase = (millis() % 400) / 400.0;
  int bounce = (int)(6 * sin(phase * 2 * PI));
  int h = eyeHeight - 6 + bounce;
  if (h < 8) h = 8;
  int yOffset = eyeY + (eyeHeight - h) / 2;
  int radius = min(eyeRadius, h / 2);
  if (radius < 1) radius = 1;
  display.fillRoundRect(leftEyeX, yOffset, eyeWidth, h, radius, SSD1306_WHITE);
  display.fillRoundRect(rightEyeX, yOffset, eyeWidth, h, radius, SSD1306_WHITE);
  display.display();
}

// ============================================================
//  10. Serial commands (sin cambios)
// ============================================================
void checkSerialCommand() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  cmd.toLowerCase();
  AgentState requested;
  bool matched = true;
  if (cmd == "idle")            requested = STATE_IDLE;
  else if (cmd == "happy")      requested = STATE_HAPPY;
  else if (cmd == "thinking")   requested = STATE_THINKING;
  else if (cmd == "surprised")  requested = STATE_SURPRISED;
  else if (cmd == "sleepy")     requested = STATE_SLEEPY;
  else if (cmd == "confused")   requested = STATE_CONFUSED;
  else if (cmd == "angry")      requested = STATE_ANGRY;
  else if (cmd == "listening")  requested = STATE_LISTENING;
  else if (cmd == "speaking")   requested = STATE_SPEAKING;
  else matched = false;
  if (matched) {
    Serial.print(F("[serial] forzando estado: "));
    Serial.println(cmd);
    setExpression(requested);
    if (requested != STATE_LISTENING && requested != STATE_SPEAKING) {
      currentStateDuration = random(3000, 6000);
    }
  } else if (cmd.length() > 0) {
    Serial.println(F("Comando no reconocido. Usa: idle, happy, thinking, surprised, sleepy, confused, angry, listening, speaking"));
  }
}

// ============================================================
//  11. MICRÓFONO I2S + VAD (NUEVO)
// ============================================================

void initI2SMic() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,  // L/R -> GND = canal izquierdo
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };

  esp_err_t err = i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("I2S driver install failed: %d\n", err);
    while (true);
  }

  err = i2s_set_pin(I2S_PORT, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("I2S set pin failed: %d\n", err);
    while (true);
  }

  // IMPORTANTE en ESP32-S3: i2s_set_clk() explícito tras set_pin
  err = i2s_set_clk(I2S_PORT, SAMPLE_RATE, I2S_BITS_PER_SAMPLE_32BIT, I2S_CHANNEL_MONO);
  if (err != ESP_OK) {
    Serial.printf("I2S set clk failed: %d\n", err);
    while (true);
  }

  i2s_zero_dma_buffer(I2S_PORT);
  Serial.println(F("I2S micrófono inicializado OK"));
}

int computeRMS(int32_t* buffer, int len) {
  long long sumSq = 0;
  for (int i = 0; i < len; i++) {
    // INMP441 entrega 24 bits en 32 bits (shift left). Tomamos los 24 bits superiores.
    int32_t sample = buffer[i] >> 8;  // ahora es 24-bit signed
    sumSq += (long long)sample * sample;
  }
  double meanSq = (double)sumSq / len;
  return (int)sqrt(meanSq);
}

void updateMicrophone() {
  size_t bytesRead = 0;
  esp_err_t err = i2s_read(I2S_PORT, (void*)i2s_read_buffer, sizeof(i2s_read_buffer), &bytesRead, portMAX_DELAY);
  if (err != ESP_OK || bytesRead == 0) return;

  int samplesRead = bytesRead / sizeof(int32_t);
  int rms = computeRMS(i2s_read_buffer, samplesRead);

  // Debug visual opcional en Serial
  if (VAD_PRINT_INTERVAL_MS > 0) {
    unsigned long now = millis();
    if (now - lastVadPrintTime >= VAD_PRINT_INTERVAL_MS) {
      int bars = rms / 100;
      if (bars > 80) bars = 80;
      Serial.print(F("RMS: ")); Serial.print(rms); Serial.print(F(" ["));
      for (int i = 0; i < bars; i++) Serial.print('#');
      Serial.println(']');
      lastVadPrintTime = now;
    }
  }

  updateVAD(rms);
}

void updateVAD(int rms) {
  unsigned long now = millis();

  if (rms >= RMS_THRESHOLD_SPEAK) {
    // Detectamos voz
    lastVoiceTime = now;
    if (!vadActive && currentState != STATE_LISTENING && currentState != STATE_SPEAKING) {
      vadActive = true;
      Serial.println(F("[VAD] Voz detectada -> LISTENING"));
      setExpression(STATE_LISTENING, true);
    }
  } else if (rms <= RMS_THRESHOLD_SILENCE) {
    // Silencio
    if (vadActive && currentState == STATE_LISTENING) {
      if (now - lastVoiceTime >= SILENCE_HOLD_MS) {
        vadActive = false;
        Serial.println(F("[VAD] Silencio sostenido -> IDLE"));
        setExpression(STATE_IDLE, true);
        // Restaurar duración autónoma para IDLE
        currentStateDuration = random(4000, 9000);
      }
    }
  }
  // Zona de histéresis (entre SILENCE y SPEAK): no hacemos nada, mantenemos estado actual
}