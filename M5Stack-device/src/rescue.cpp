#include <M5Unified.h>
#include <driver/rmt.h>
#include <driver/gpio.h>
#include <SD.h>

void setup() {
  Serial.begin(115200);
  auto config = M5.config();
  config.clear_display = true;
  config.output_power = true;
  config.internal_imu = true;
  config.internal_rtc = true;
  config.internal_mic = true;
  config.internal_spk = true;
  config.led_brightness = 0;
  Serial.println("recovery: before M5.begin");
  M5.begin(config);
  Serial.println("recovery: after M5.begin");
  Serial.println("recovery: before RMT");
  pinMode(15, OUTPUT_OPEN_DRAIN);
  rmt_config_t rmt = {};
  rmt.rmt_mode = RMT_MODE_TX;
  rmt.channel = RMT_CHANNEL_0;
  rmt.gpio_num = GPIO_NUM_15;
  rmt.clk_div = 2;
  rmt.mem_block_num = 1;
  rmt.tx_config.loop_en = false;
  rmt.tx_config.carrier_en = false;
  rmt.tx_config.idle_output_en = true;
  rmt.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;
  rmt_config(&rmt);
  rmt_driver_install(rmt.channel, 0, 0);
  Serial.println("recovery: after RMT");
  Serial.println("recovery: before SD");
  SD.begin(4, SPI, 25000000);
  Serial.println("recovery: after SD");
  M5.Display.setRotation(0);
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.drawString("FIRE RECOVERY", 42, 70);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.drawString("LCD and hardware boot OK", 72, 108);
  M5.Display.drawString("Press A/B/C to test buttons", 62, 132);
  Serial.println("FIRE recovery firmware started");
}

void loop() {
  M5.update();
  if (M5.BtnA.wasPressed()) Serial.println("A pressed");
  if (M5.BtnB.wasPressed()) Serial.println("B pressed");
  if (M5.BtnC.wasPressed()) Serial.println("C pressed");
  delay(25);
}
