/*
  Ojos de robot - ESP32 + OLED SSD1306 (128x64, I2C)
  ---------------------------------------------------
  Conexiones (NodeMCU-32S):
    OLED VCC -> 3V3
    OLED GND -> GND
    OLED SCL -> P22
    OLED SDA -> P21

  Librerías necesarias (Arduino IDE > Administrador de bibliotecas):
    - Adafruit SSD1306
    - Adafruit GFX Library
*/

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C   // dirección I2C típica; si no funciona, prueba 0x3D

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// --- Configuración de los ojos ---
int eyeWidth   = 40;   // ancho de cada ojo
int eyeHeight  = 40;   // alto de cada ojo (estado normal, abierto)
int eyeRadius  = 10;   // qué tan redondeadas son las esquinas
int eyeSpacing = 20;   // separación entre los dos ojos

int leftEyeX, rightEyeX, eyeY;

// --- Control de parpadeo ---
unsigned long lastBlinkTime = 0;
const unsigned long blinkInterval = 3000; // cada 3 segundos
const unsigned long blinkDuration = 100;  // qué tan rápido cierra/abre (ms), en total
bool isBlinking = false;

void setup() {
  Serial.begin(115200);

  Wire.begin(21, 22);      // SDA, SCL
  Wire.setClock(400000);   // I2C rápido (400kHz) para que la animación no se vea lenta

  if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
    Serial.println(F("Error: no se detectó la pantalla OLED"));
    while (true); // detenido si falla
  }

  // Posición centrada de los ojos
  int totalWidth = (eyeWidth * 2) + eyeSpacing;
  leftEyeX  = (SCREEN_WIDTH - totalWidth) / 2;
  rightEyeX = leftEyeX + eyeWidth + eyeSpacing;
  eyeY = (SCREEN_HEIGHT - eyeHeight) / 2;

  display.clearDisplay();
  drawEyes(eyeHeight);
}

void loop() {
  unsigned long now = millis();

  // Es hora de parpadear
  if (!isBlinking && (now - lastBlinkTime >= blinkInterval)) {
    blink();
    lastBlinkTime = now;
  }
}

void drawEyes(int currentHeight) {
  display.clearDisplay();

  int yOffset = eyeY + (eyeHeight - currentHeight) / 2;

  // Evita que el radio sea más grande que la mitad del alto actual (si no, se deforma al cerrar)
  int radius = min(eyeRadius, currentHeight / 2);
  if (radius < 1) radius = 1;

  // Ojo izquierdo
  display.fillRoundRect(leftEyeX, yOffset, eyeWidth, currentHeight, radius, SSD1306_WHITE);
  // Ojo derecho
  display.fillRoundRect(rightEyeX, yOffset, eyeWidth, currentHeight, radius, SSD1306_WHITE);

  display.display();
}

void blink() {
  isBlinking = true;

  const int steps = 5;
  int stepSize = eyeHeight / steps;
  int stepDelay = blinkDuration / steps; // ms por paso

  // Cerrar el ojo (de altura completa a casi 0)
  for (int h = eyeHeight; h >= 2; h -= stepSize) {
    drawEyes(h);
    delay(stepDelay);
  }

  delay(40); // ojo cerrado un instante

  // Abrir el ojo (de vuelta a altura completa)
  for (int h = 2; h <= eyeHeight; h += stepSize) {
    drawEyes(h);
    delay(stepDelay);
  }
  drawEyes(eyeHeight); // asegurar altura exacta al final

  drawEyes(eyeHeight); // asegurar que queda completamente abierto
  isBlinking = false;
}
