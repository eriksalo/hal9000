/**
 * HAL 9000 Display Interface
 * For VIEWE 2.1" Round Touch Knob Display
 *
 * Features:
 * - Animated HAL eye with pulsing effect
 * - Touch to talk to HAL
 * - Rotary encoder for volume
 * - WiFi connection to Raspberry Pi API
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <lvgl.h>
#include "display_config.h"
#include "secrets.h"

// Display instance
static LGFX lcd;
static lv_display_t *lvgl_display = nullptr;

// Draw buffers
#define DRAW_BUF_SIZE (480 * 40 * sizeof(lv_color_t))
static uint8_t *draw_buf1;
static uint8_t *draw_buf2;

// UI elements
static lv_obj_t *hal_eye_outer = nullptr;
static lv_obj_t *hal_eye_inner = nullptr;
static lv_obj_t *hal_eye_center = nullptr;
static lv_obj_t *status_label = nullptr;
static lv_obj_t *response_label = nullptr;

// Animation
static lv_anim_t eye_pulse_anim;
static bool is_speaking = false;
static bool is_listening = false;

// Encoder state
volatile int encoder_pos = 50;  // Volume 0-100
static int last_encoder_a = HIGH;

// API settings
String api_host = HAL_API_HOST;
int api_port = HAL_API_PORT;

// Forward declarations
void setup_ui();
void create_hal_eye();
void update_status(const char* status);
void start_eye_animation();
void eye_pulse_callback(void *var, int32_t value);
void on_eye_touch(lv_event_t *e);
void send_chat_message(const char* message);
void IRAM_ATTR encoder_isr();

// LVGL display flush callback
void lvgl_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map) {
    uint32_t w = (area->x2 - area->x1 + 1);
    uint32_t h = (area->y2 - area->y1 + 1);

    lcd.startWrite();
    lcd.setAddrWindow(area->x1, area->y1, w, h);
    lcd.writePixels((uint16_t *)px_map, w * h);
    lcd.endWrite();

    lv_display_flush_ready(disp);
}

// LVGL touch read callback
void lvgl_touch_cb(lv_indev_t *indev, lv_indev_data_t *data) {
    uint16_t x, y;
    if (lcd.getTouch(&x, &y)) {
        data->point.x = x;
        data->point.y = y;
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

void setup() {
    Serial.begin(115200);
    Serial.println("HAL 9000 Display Starting...");

    // Initialize display
    lcd.init();
    lcd.setRotation(0);
    lcd.setBrightness(200);
    lcd.fillScreen(TFT_BLACK);

    // Initialize LVGL
    lv_init();

    // Allocate draw buffers in PSRAM
    draw_buf1 = (uint8_t *)heap_caps_malloc(DRAW_BUF_SIZE, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    draw_buf2 = (uint8_t *)heap_caps_malloc(DRAW_BUF_SIZE, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);

    if (!draw_buf1 || !draw_buf2) {
        Serial.println("Failed to allocate draw buffers!");
        // Fallback to internal RAM
        draw_buf1 = (uint8_t *)malloc(DRAW_BUF_SIZE);
        draw_buf2 = draw_buf1 ? (uint8_t *)malloc(DRAW_BUF_SIZE) : nullptr;
    }

    // Create LVGL display
    lvgl_display = lv_display_create(480, 480);
    lv_display_set_flush_cb(lvgl_display, lvgl_flush_cb);
    lv_display_set_buffers(lvgl_display, draw_buf1, draw_buf2, DRAW_BUF_SIZE, LV_DISPLAY_RENDER_MODE_PARTIAL);

    // Create touch input device
    lv_indev_t *indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, lvgl_touch_cb);

    // Setup encoder pins
    pinMode(ENCODER_A, INPUT_PULLUP);
    pinMode(ENCODER_B, INPUT_PULLUP);
    pinMode(ENCODER_BTN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(ENCODER_A), encoder_isr, CHANGE);

    // Create UI
    setup_ui();
    update_status("Connecting to WiFi...");

    // Connect to WiFi
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int wifi_attempts = 0;
    while (WiFi.status() != WL_CONNECTED && wifi_attempts < 30) {
        delay(500);
        Serial.print(".");
        wifi_attempts++;
        lv_timer_handler();
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi connected!");
        Serial.print("IP: ");
        Serial.println(WiFi.localIP());
        update_status("HAL 9000 Online");
    } else {
        Serial.println("\nWiFi connection failed!");
        update_status("WiFi Failed");
    }

    // Start eye animation
    start_eye_animation();
}

void loop() {
    lv_timer_handler();
    delay(5);

    // Check encoder button
    static bool last_btn = HIGH;
    bool btn = digitalRead(ENCODER_BTN);
    if (btn == LOW && last_btn == HIGH) {
        // Button pressed - toggle listening mode
        is_listening = !is_listening;
        if (is_listening) {
            update_status("Listening...");
        } else {
            update_status("HAL 9000 Online");
        }
    }
    last_btn = btn;
}

void setup_ui() {
    // Set black background
    lv_obj_set_style_bg_color(lv_screen_active(), lv_color_black(), 0);

    // Create HAL eye
    create_hal_eye();

    // Status label at bottom
    status_label = lv_label_create(lv_screen_active());
    lv_obj_set_style_text_color(status_label, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_16, 0);
    lv_label_set_text(status_label, "Initializing...");
    lv_obj_align(status_label, LV_ALIGN_BOTTOM_MID, 0, -40);

    // Response label (hidden initially)
    response_label = lv_label_create(lv_screen_active());
    lv_obj_set_style_text_color(response_label, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_text_font(response_label, &lv_font_montserrat_14, 0);
    lv_label_set_long_mode(response_label, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(response_label, 400);
    lv_label_set_text(response_label, "");
    lv_obj_align(response_label, LV_ALIGN_TOP_MID, 0, 40);
    lv_obj_add_flag(response_label, LV_OBJ_FLAG_HIDDEN);
}

void create_hal_eye() {
    int center_x = 240;
    int center_y = 240;

    // Outer glow ring (dark red)
    hal_eye_outer = lv_obj_create(lv_screen_active());
    lv_obj_set_size(hal_eye_outer, 280, 280);
    lv_obj_set_style_radius(hal_eye_outer, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(hal_eye_outer, lv_color_hex(0x400000), 0);
    lv_obj_set_style_border_width(hal_eye_outer, 0, 0);
    lv_obj_set_style_shadow_width(hal_eye_outer, 60, 0);
    lv_obj_set_style_shadow_color(hal_eye_outer, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_shadow_spread(hal_eye_outer, 20, 0);
    lv_obj_set_style_shadow_opa(hal_eye_outer, LV_OPA_70, 0);
    lv_obj_align(hal_eye_outer, LV_ALIGN_CENTER, 0, 0);
    lv_obj_remove_flag(hal_eye_outer, LV_OBJ_FLAG_SCROLLABLE);

    // Main eye circle (red gradient effect)
    hal_eye_inner = lv_obj_create(lv_screen_active());
    lv_obj_set_size(hal_eye_inner, 200, 200);
    lv_obj_set_style_radius(hal_eye_inner, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(hal_eye_inner, lv_color_hex(0xCC0000), 0);
    lv_obj_set_style_border_width(hal_eye_inner, 4, 0);
    lv_obj_set_style_border_color(hal_eye_inner, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_shadow_width(hal_eye_inner, 30, 0);
    lv_obj_set_style_shadow_color(hal_eye_inner, lv_color_hex(0xFF0000), 0);
    lv_obj_align(hal_eye_inner, LV_ALIGN_CENTER, 0, 0);
    lv_obj_remove_flag(hal_eye_inner, LV_OBJ_FLAG_SCROLLABLE);

    // Center bright spot (yellow/white)
    hal_eye_center = lv_obj_create(lv_screen_active());
    lv_obj_set_size(hal_eye_center, 60, 60);
    lv_obj_set_style_radius(hal_eye_center, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(hal_eye_center, lv_color_hex(0xFFFF00), 0);
    lv_obj_set_style_border_width(hal_eye_center, 0, 0);
    lv_obj_set_style_shadow_width(hal_eye_center, 20, 0);
    lv_obj_set_style_shadow_color(hal_eye_center, lv_color_hex(0xFFFF00), 0);
    lv_obj_align(hal_eye_center, LV_ALIGN_CENTER, 0, 0);
    lv_obj_remove_flag(hal_eye_center, LV_OBJ_FLAG_SCROLLABLE);

    // Add touch event to eye
    lv_obj_add_flag(hal_eye_inner, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(hal_eye_inner, on_eye_touch, LV_EVENT_CLICKED, NULL);
}

void start_eye_animation() {
    lv_anim_init(&eye_pulse_anim);
    lv_anim_set_var(&eye_pulse_anim, hal_eye_outer);
    lv_anim_set_values(&eye_pulse_anim, 50, 80);
    lv_anim_set_duration(&eye_pulse_anim, 2000);
    lv_anim_set_repeat_count(&eye_pulse_anim, LV_ANIM_REPEAT_INFINITE);
    lv_anim_set_playback_duration(&eye_pulse_anim, 2000);
    lv_anim_set_exec_cb(&eye_pulse_anim, eye_pulse_callback);
    lv_anim_start(&eye_pulse_anim);
}

void eye_pulse_callback(void *var, int32_t value) {
    lv_obj_t *obj = (lv_obj_t *)var;
    lv_obj_set_style_shadow_spread(obj, value, 0);
    lv_obj_set_style_shadow_opa(obj, LV_OPA_50 + (value - 50), 0);
}

void update_status(const char* status) {
    if (status_label) {
        lv_label_set_text(status_label, status);
    }
}

void on_eye_touch(lv_event_t *e) {
    Serial.println("Eye touched!");
    update_status("Talking to HAL...");

    // Send a test message
    send_chat_message("Hello HAL, what do you see?");
}

void send_chat_message(const char* message) {
    if (WiFi.status() != WL_CONNECTED) {
        update_status("No WiFi connection");
        return;
    }

    HTTPClient http;
    String url = "http://" + api_host + ":" + String(api_port) + "/api/chat";

    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    // Create JSON payload
    JsonDocument doc;
    doc["message"] = message;
    JsonArray history = doc["history"].to<JsonArray>();

    String payload;
    serializeJson(doc, payload);

    int httpCode = http.POST(payload);

    if (httpCode > 0) {
        String response = http.getString();
        Serial.println("Response: " + response);

        // Parse response
        JsonDocument respDoc;
        DeserializationError error = deserializeJson(respDoc, response);

        if (!error) {
            const char* hal_response = respDoc["response"];
            if (hal_response) {
                // Show response briefly
                lv_obj_remove_flag(response_label, LV_OBJ_FLAG_HIDDEN);
                lv_label_set_text(response_label, hal_response);
                update_status("HAL 9000 Online");

                // Hide response after 5 seconds
                // (In production, use lv_timer for this)
            }
        }
    } else {
        Serial.println("HTTP Error: " + String(httpCode));
        update_status("Connection Error");
    }

    http.end();
}

void IRAM_ATTR encoder_isr() {
    int a = digitalRead(ENCODER_A);
    int b = digitalRead(ENCODER_B);

    if (a != last_encoder_a) {
        if (b != a) {
            encoder_pos = min(100, encoder_pos + 1);
        } else {
            encoder_pos = max(0, encoder_pos - 1);
        }
    }
    last_encoder_a = a;
}
