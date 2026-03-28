const byte pinCount = 6;
const byte pins[pinCount] = {2, 3, 4, 5, 6, 7};
boolean states[pinCount];
unsigned long result;
unsigned long lastResult = 999999; // заведомо невозможное значение

void setup() {
  Serial.begin(9600);
  for (byte i = 0; i < pinCount; i++) {
    // INPUT_PULLUP: встроенная подтяжка к +5В — пин не "плавает"
    // когда геркон разомкнут → HIGH (1), замкнут → LOW (0)
    pinMode(pins[i], INPUT_PULLUP);
  }
}

void loop() {
  result = 0;
  unsigned long multiplier = 1;

  for (byte i = 0; i < pinCount; i++) {
    // INPUT_PULLUP инвертирует логику: LOW = нажато = 1
    states[i] = digitalRead(pins[i]) == LOW;
    result += states[i] * multiplier;
    multiplier *= 10;
  }

  // Отправляем только при изменении — не спамим порт
  if (result != lastResult) {
    Serial.println(result);
    lastResult = result;
  }

  delay(50); // 50 мс — быстрый отклик, без дребезга
}
