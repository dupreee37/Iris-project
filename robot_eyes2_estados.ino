/*
  Ojos de robot - ESP32 + OLED SSD1306 (128x64, I2C)
  ---------------------------------------------------
  ETAPA 2: Sistema de expresiones y estados.

  Conexiones (NodeMCU-32S) — SIN CAMBIOS respecto al sketch original:
    OLED VCC -> 3V3
    OLED GND -> GND
    OLED SCL -> P22
    OLED SDA -> P21

  Librerías necesarias (Arduino IDE > Administrador de bibliotecas):
    - Adafruit SSD1306
    - Adafruit GFX Library

  ARQUITECTURA
  ------------
  FASE ACTUAL:  ESP32 elige solo entre expresiones (aleatorio con pesos) -> OLED
  FASE FUTURA:  Raspberry Pi / IA decide el estado -> lo manda por Serial (o luego
                WiFi/MQTT) -> setExpression(x) -> OLED

  El "cerebro" (lo que decide qué cara mostrar) está separado del "cuerpo"
  (las funciones que dibujan cada cara). Cuando más adelante llegue la IA,
  lo único que cambia es QUIÉN llama a setExpression(): hoy lo llama un
  temporizador aleatorio (chooseNextAutonomousState), en el futuro lo va a
  llamar el parser de Serial/WiFi con el estado que decida el agente.
*/

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C   // dirección I2C típica; si no funciona, prueba 0x3D

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============================================================
//  CONFIGURACIÓN BASE DE LOS OJOS (igual que el sketch original)
// ============================================================
int eyeWidth   = 40;   // ancho de cada ojo
int eyeHeight  = 40;   // alto de cada ojo (estado normal, abierto)
int eyeRadius  = 10;   // qué tan redondeadas son las esquinas
int eyeSpacing = 20;   // separación entre los dos ojos

int leftEyeX, rightEyeX, eyeY;
int leftEyeCX, rightEyeCX, eyeCY; // centros (útiles para círculos/arcos)

// ============================================================
//  1. ESTADOS DEL AGENTE
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
  STATE_COUNT           // truco: cantidad total de estados (siempre al final)
};

AgentState currentState = STATE_IDLE;

// Config de cada estado usado en el pool AUTÓNOMO (LISTENING y SPEAKING
// quedan fuera del sorteo a propósito: son para control externo futuro).
struct StateConfig {
  AgentState state;
  const char* name;
  int weight;          // mayor = más probable
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
const unsigned long idleBlinkInterval = 3000; // sólo aplica durante IDLE
bool isTransitioning = false;

// ============================================================
//  DECLARACIONES ADELANTADAS
// ============================================================
void setExpression(AgentState newState, bool withTransition = true);
void renderExpression(AgentState state);
void chooseNextAutonomousState();
void playTransitionBlink();
void checkSerialCommand();

void drawIdle();
void drawHappy();
void drawThinking();
void drawSurprised();
void drawSleepy();
void drawConfused();
void drawAngry();
void drawListening();
void drawSpeaking();

// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);

  Wire.begin(21, 22);      // SDA, SCL
  Wire.setClock(400000);   // I2C rápido (400kHz)

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

  randomSeed(esp_random());

  display.clearDisplay();
  currentState = STATE_IDLE;
  stateStartTime = millis();
  currentStateDuration = random(4000, 9000);
  renderExpression(currentState);

  Serial.println(F("Agente listo. Estados disponibles por Serial:"));
  Serial.println(F("idle, happy, thinking, surprised, sleepy, confused, angry, listening, speaking"));
}

// ============================================================
//  LOOP  -> un único punto de entrada: updateAgent()
// ============================================================
void loop() {
  updateAgent();
  checkSerialCommand();
}

// ============================================================
//  3. updateAgent(): el "reloj" que decide cuándo pasa algo
// ============================================================
void updateAgent() {
  unsigned long now = millis();

  // --- Micro-parpadeo sólo durante IDLE (la cara de descanso) ---
  if (currentState == STATE_IDLE && !isTransitioning) {
    if (now - lastIdleBlinkTime >= idleBlinkInterval) {
      quickBlinkOnly();
      lastIdleBlinkTime = now;
    }
  }

  // --- Animaciones continuas de algunos estados (no cambian de estado,
  //     sólo re-dibujan su propia cara con una fase animada) ---
  if (!isTransitioning) {
    renderExpression(currentState); // redibuja cada frame para estados con animación (thinking, listening, speaking)
  }

  // --- ¿Se venció el tiempo del estado actual? Sólo se auto-cambia si
  //     el estado actual pertenece al pool autónomo. LISTENING/SPEAKING,
  //     al ser forzados externamente, no vencen solos: se quedan hasta
  //     que alguien (por ahora, vos por Serial) mande el próximo estado. ---
  bool isAutonomousState = (currentState != STATE_LISTENING && currentState != STATE_SPEAKING);

  if (isAutonomousState && (now - stateStartTime >= currentStateDuration)) {
    chooseNextAutonomousState();
  }
}

// ============================================================
//  4. Selección aleatoria con pesos, evitando repetir el mismo estado
// ============================================================
void chooseNextAutonomousState() {
  int totalWeight = 0;
  for (int i = 0; i < autonomousPoolSize; i++) {
    if (autonomousPool[i].state == currentState) continue; // no repetir
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
//  5. setExpression(): el punto único que TODO el mundo debe llamar
//     (hoy el sorteo aleatorio, mañana el parser de la IA)
// ============================================================
void setExpression(AgentState newState, bool withTransition) {
  if (withTransition) {
    playTransitionBlink();
  }
  currentState = newState;
  stateStartTime = millis();
  renderExpression(currentState);
}

// ============================================================
//  6. Transición: parpadeo genérico entre expresiones
// ============================================================
void playTransitionBlink() {
  isTransitioning = true;

  const int steps = 5;
  int stepSize = eyeHeight / steps;
  int stepDelay = 20;

  // Cerrar (cualquiera sea la expresión actual, cerramos con el rect base)
  for (int h = eyeHeight; h >= 2; h -= stepSize) {
    drawLidsHeight(h);
    delay(stepDelay);
  }
  delay(60); // instante cerrado

  isTransitioning = false;
  // La apertura hacia la cara nueva la hace renderExpression() al volver
  // de setExpression(); no hace falta "abrir" genérico porque cada cara
  // tiene su propia forma final.
}

// Dibuja los "párpados" cerrándose como rectángulo genérico (independiente
// de qué expresión sigue). Es sólo el efecto visual del cierre.
void drawLidsHeight(int currentHeight) {
  display.clearDisplay();
  int yOffset = eyeY + (eyeHeight - currentHeight) / 2;
  int radius = min(eyeRadius, currentHeight / 2);
  if (radius < 1) radius = 1;

  display.fillRoundRect(leftEyeX, yOffset, eyeWidth, currentHeight, radius, SSD1306_WHITE);
  display.fillRoundRect(rightEyeX, yOffset, eyeWidth, currentHeight, radius, SSD1306_WHITE);
  display.display();
}

// Parpadeo rápido que NO cambia de estado (usado en reposo durante IDLE)
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
//  7. Dispatcher: qué función de dibujo corresponde a cada estado
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
    default:                drawIdle();      break;
  }
}

// ============================================================
//  8. HELPER: arco grueso aproximado (para HAPPY / SLEEPY)
//     Dibuja puntos a lo largo de un arco de círculo y los engrosa
//     con pequeños círculos, ya que Adafruit_GFX no tiene arcos nativos.
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
//  9. EXPRESIONES
// ============================================================

// --- IDLE: los ojos rectangulares originales, abiertos ---
void drawIdle() {
  display.clearDisplay();
  int radius = eyeRadius;
  display.fillRoundRect(leftEyeX, eyeY, eyeWidth, eyeHeight, radius, SSD1306_WHITE);
  display.fillRoundRect(rightEyeX, eyeY, eyeWidth, eyeHeight, radius, SSD1306_WHITE);
  display.display();
}

// --- HAPPY: arcos hacia arriba tipo "⌒ ⌒" (ojos sonrientes/cerrados) ---
void drawHappy() {
  display.clearDisplay();
  int r = eyeWidth / 2;
  int thickness = 4;
  // arco superior: de 200° a 340° dibuja una "gorra" hacia arriba
  drawThickArc(leftEyeCX,  eyeCY + r / 2, r, 200, 340, thickness);
  drawThickArc(rightEyeCX, eyeCY + r / 2, r, 200, 340, thickness);
  display.display();
}

// --- SLEEPY: arcos hacia abajo tipo "⌣ ⌣" (párpados caídos) + más lento ---
void drawSleepy() {
  display.clearDisplay();
  int r = eyeWidth / 2;
  int thickness = 3;
  drawThickArc(leftEyeCX,  eyeCY - r / 2, r, 20, 160, thickness);
  drawThickArc(rightEyeCX, eyeCY - r / 2, r, 20, 160, thickness);
  display.display();
}

// --- SURPRISED: círculos grandes bien abiertos ---
void drawSurprised() {
  display.clearDisplay();
  int r = (eyeWidth / 2) + 4; // más grandes que el ojo normal
  display.fillCircle(leftEyeCX, eyeCY, r, SSD1306_WHITE);
  display.fillCircle(rightEyeCX, eyeCY, r, SSD1306_WHITE);
  display.display();
}

// --- THINKING: ojos entornados (rectángulo bajo) + 3 puntitos animados ---
void drawThinking() {
  display.clearDisplay();
  int thinHeight = eyeHeight / 3;
  int yOffset = eyeY + (eyeHeight - thinHeight) / 2;
  int radius = min(eyeRadius, thinHeight / 2);
  if (radius < 1) radius = 1;

  display.fillRoundRect(leftEyeX, yOffset, eyeWidth, thinHeight, radius, SSD1306_WHITE);
  display.fillRoundRect(rightEyeX, yOffset, eyeWidth, thinHeight, radius, SSD1306_WHITE);

  // 3 puntos "procesando", uno se prende por turno según el tiempo
  int dotsY = eyeY + eyeHeight + 10;
  int dotsCenterX = SCREEN_WIDTH / 2;
  int spacing = 10;
  int activeDot = (millis() / 300) % 3; // cambia cada 300ms

  for (int i = -1; i <= 1; i++) {
    int dx = dotsCenterX + i * spacing;
    int radius2 = (i + 1 == activeDot) ? 3 : 1;
    display.fillCircle(dx, dotsY, radius2, SSD1306_WHITE);
  }
  display.display();
}

// --- CONFUSED: asimétrico (un ojo normal, el otro con "ceja" inclinada) ---
void drawConfused() {
  display.clearDisplay();
  int r = eyeWidth / 2;

  // Ojo izquierdo: círculo normal
  display.fillCircle(leftEyeCX, eyeCY, r - 2, SSD1306_WHITE);

  // Ojo derecho: más chico, con una línea de "ceja" inclinada arriba
  display.fillCircle(rightEyeCX, eyeCY + 3, r - 6, SSD1306_WHITE);
  display.drawLine(rightEyeCX - r + 2, eyeCY - r - 2, rightEyeCX + r - 6, eyeCY - r + 6, SSD1306_WHITE);
  display.drawLine(rightEyeCX - r + 2, eyeCY - r - 1, rightEyeCX + r - 6, eyeCY - r + 7, SSD1306_WHITE);

  display.display();
}

// --- ANGRY / WARNING: trapecios inclinados hacia el centro (cejas fruncidas) ---
void drawAngry() {
  display.clearDisplay();
  int h = eyeHeight / 2;
  int yTop = eyeCY - h / 2;
  int yBot = eyeCY + h / 2;

  // Ojo izquierdo: más alto hacia afuera, más bajo hacia el centro
  display.fillTriangle(leftEyeX, yTop,
                        leftEyeX + eyeWidth, yBot,
                        leftEyeX, yBot, SSD1306_WHITE);
  display.fillTriangle(leftEyeX, yTop,
                        leftEyeX + eyeWidth, yTop + h / 2,
                        leftEyeX + eyeWidth, yBot, SSD1306_WHITE);

  // Ojo derecho: espejado (más bajo hacia el centro también)
  display.fillTriangle(rightEyeX + eyeWidth, yTop,
                        rightEyeX, yBot,
                        rightEyeX + eyeWidth, yBot, SSD1306_WHITE);
  display.fillTriangle(rightEyeX + eyeWidth, yTop,
                        rightEyeX, yTop + h / 2,
                        rightEyeX, yBot, SSD1306_WHITE);
  display.display();
}

// --- LISTENING: círculos con un anillo pulsante alrededor (atento) ---
void drawListening() {
  display.clearDisplay();
  int r = eyeWidth / 2 - 2;
  display.fillCircle(leftEyeCX, eyeCY, r, SSD1306_WHITE);
  display.fillCircle(rightEyeCX, eyeCY, r, SSD1306_WHITE);

  // anillo que "respira": su radio crece y decrece con el tiempo
  float phase = (millis() % 1000) / 1000.0; // 0..1
  int pulseR = r + 4 + (int)(6 * sin(phase * 2 * PI));
  display.drawCircle(leftEyeCX, eyeCY, pulseR, SSD1306_WHITE);
  display.drawCircle(rightEyeCX, eyeCY, pulseR, SSD1306_WHITE);

  display.display();
}

// --- SPEAKING: ojos que "laten" en altura simulando energía al hablar ---
void drawSpeaking() {
  display.clearDisplay();
  float phase = (millis() % 400) / 400.0; // ciclo rápido
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
//  10. Gancho de prueba por Serial (esto es lo que el día de mañana
//      va a reemplazar el parser de comandos de la Raspberry Pi)
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
    // Si lo forzado es un estado del pool autónomo, le damos una duración
    // nueva para que no cambie al toque solo:
    if (requested != STATE_LISTENING && requested != STATE_SPEAKING) {
      currentStateDuration = random(3000, 6000);
    }
  } else if (cmd.length() > 0) {
    Serial.println(F("Comando no reconocido. Usa: idle, happy, thinking, surprised, sleepy, confused, angry, listening, speaking"));
  }
}
