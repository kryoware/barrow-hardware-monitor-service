// Barrow OLED stats: Leonardo + SSD1306 128x64 (I2C 0x3C) + 16 NeoPixels on pin 10.
// Host (barrow.py) sends one '\n'-terminated frame per second:
//   C<temp>c<load>%|CHC<mhz>|G<gpu temp>g<gpu load>%|R<ram GB>|N<gpu name>|CPU:<name>GPU:Intel
// Boots with a ~4 s nyan cat animation, then pages rotate every 18 s:
// D1 TEMP, D2 ClocK, D3 USAGE, D4 CPU/GPU/SYSRAM overview.
// The screen blanks after 10 s without data.
#include <Adafruit_NeoPixel.h>
#include <Adafruit_SSD1306.h>
#include "logo.h"

Adafruit_SSD1306 display(128, 64, &Wire, -1);
Adafruit_NeoPixel strip(16, 10, NEO_GRB + NEO_KHZ800);

char buf[160], cpu[20], temp[6], load[6], mhz[6], gtemp[6], gload[6], ram[6], gpu[22];
byte len, page = 1;
unsigned long seen, flipped;
bool on;

void setup() {
  Serial.begin(115200);
  strip.begin();
  strip.show();
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.setRotation(2);
  display.setTextWrap(false);
  display.setTextColor(SSD1306_WHITE);
  for (byte f = 0; f < 60; f++) {
    nyan(f);
    delay(40);
  }
  display.clearDisplay();
  display.display();
}

// s: 0 dot, 1 small plus, 2 big hollow plus, 3 four outer dots.
void star(int x, int y, byte s) {
  if (s < 2) display.drawPixel(x, y, SSD1306_WHITE);
  for (byte d = s / 3 + 1; d <= min(s, 2); d++) {
    display.drawPixel(x - d, y, SSD1306_WHITE);
    display.drawPixel(x + d, y, SSD1306_WHITE);
    display.drawPixel(x, y - d, SSD1306_WHITE);
    display.drawPixel(x, y + d, SSD1306_WHITE);
  }
}

void nyan(byte f) {
  const byte starY[] = {3, 58, 7, 61, 1, 56}, legs[] = {3, 7, 16, 22};
  byte p = (f / 2) & 1;
  int x0 = 60, y0 = 10 + 2 * p;
  display.clearDisplay();
  for (byte i = 0; i < 6; i++) star(127 - (f * 5 + i * 25) % 150, starY[i], (f / 2 + i) % 4);
  // 1-bit rainbow: solid and 50% dithered stripes, waving in 8 px segments.
  for (int x = 0; x < x0 + 4; x++)
    for (byte r = 0; r < 36; r++)
      if ((r / 6) % 2 == 0 || (x + r) % 2 == 0)
        display.drawPixel(x, 12 + ((x / 8 + p) & 1) * 2 + r, SSD1306_WHITE);
  for (byte r = 0; r < 20; r++)
    for (byte c = 0; c < 30; c++) {
      char ch = pgm_read_byte(&cat[r][c]);
      if (ch != ' ') display.fillRect(x0 + 2 * c, y0 + 2 * r, 2, 2, ch == '#' ? SSD1306_WHITE : SSD1306_BLACK);
    }
  for (byte lx : legs) display.fillRect(x0 + 2 * (lx + p), 48, 4, 4, SSD1306_WHITE);
  display.display();
}

// Copies the text after key up to end (or size - 1 chars) into out; "--" if missing.
void field(const char *key, char end, char *out, byte size) {
  const char *p = strstr(buf, key);
  byte n = 0;
  if (p)
    for (p += strlen(key); *p && *p != end && n < size - 1; p++) out[n++] = *p;
  out[n] = 0;
  if (!n) strcpy(out, "--");
}

void parse() {
  field("C", 'c', temp, sizeof temp);
  field("c", '%', load, sizeof load);
  field("CHC", '|', mhz, sizeof mhz);
  field("|G", 'g', gtemp, sizeof gtemp);
  field("g", '%', gload, sizeof gload);
  field("|R", '|', ram, sizeof ram);
  field("|N", '|', gpu, sizeof gpu);
  // The name's first line is padded to 21 chars, so the first 19 never reach "GPU:".
  field("CPU:", 0, cpu, sizeof cpu);
  for (byte n = strlen(cpu); n && cpu[n - 1] == ' ';) cpu[--n] = 0;
}

// Label bottom-left, value as large as fits, unit top-aligned after it.
void big(const char *label, const char *val, const char *unit) {
  byte s = min(4, (128 - 34 - 6 * strlen(unit)) / (6 * strlen(val)));
  display.setCursor(0, 45);
  display.print(label);
  display.setTextSize(s);
  display.setCursor(34, 52 - 7 * s);
  display.print(val);
  display.setTextSize(1);
  display.setCursor(display.getCursorX(), 52 - 7 * s);
  display.print(unit);
}

void row(byte y, const char *label, const char *t, const char *l) {
  display.setCursor(0, y + 7);
  display.print(label);
  display.setTextSize(2);
  display.setCursor(24, y);
  display.print(t);
  display.setTextSize(1);
  display.print("\xF7" "C");
  display.setTextSize(2);
  display.setCursor(116 - 12 * strlen(l), y);
  display.print(l);
  display.setTextSize(1);
  display.print('%');
}

void draw() {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.print(cpu);
  display.setCursor(116, 0);
  display.print('D');
  display.print(page);
  if (page == 1) big("TEMP", temp, "\xF7" "C");
  else if (page == 2) big("ClocK", mhz, "MHz");
  else if (page == 3) big("USAGE", load, "%");
  else {
    row(11, "CPU", temp, load);
    display.setCursor(0, 29);
    display.print(gpu);
    row(39, "GPU", gtemp, gload);
    display.setCursor(0, 56);
    display.print("SYSRAM ");
    display.print(ram);
    display.print("GB");
  }
  display.display();
}

void loop() {
  bool dirty = false;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') {
      buf[len] = 0;
      len = 0;
      parse();
      seen = millis();
      dirty = on = true;
    } else if (len < sizeof buf - 1) {
      buf[len++] = ch;
    }
  }
  if (millis() - flipped >= 18000) {
    flipped = millis();
    page = page % 4 + 1;
    dirty = true;
  }
  if (on && millis() - seen > 10000) {
    on = false;
    display.clearDisplay();
    display.display();
  } else if (on && dirty) {
    draw();
  }
}
