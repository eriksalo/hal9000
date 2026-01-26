/**
 * HAL 9000 Display Interface
 * For VIEWE 2.1" Round Touch Knob Display
 * Using LVGL 8.x and LovyanGFX
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

// LVGL objects
static lv_disp_draw_buf_t draw_buf;
static lv_disp_drv_t disp_drv;
static lv_indev_drv_t indev_drv;

// Draw buffers
#define DRAW_BUF_SIZE (480 * 40)
static lv_color_t *buf1 = nullptr;
static lv_color_t *buf2 = nullptr;

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
volatile int encoder_pos = 50;
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
void lvgl_flush_cb(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
    uint32_t w = (area->x2 - area->x1 + 1);
    uint32_t h = (area->y2 - area->y1 + 1);

    lcd.startWrite();
    lcd.setAddrWindow(area->x1, area->y1, w, h);
    lcd.writePixels((uint16_t *)color_p, w * h);
    lcd.endWrite();

    lv_disp_flush_ready(disp);
}

// LVGL touch read callback
void lvgl_touch_cb(lv_indev_drv_t *indev, lv_indev_data_t *data) {
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
    delay(500);
    Serial.println("\n\nHAL 9000 Display Starting...");
    Serial.printf("Free heap: %d\n", ESP.getFreeHeap());
    Serial.printf("PSRAM: %d\n", ESP.getPsramSize());

    // Initialize display
    Serial.println("Initializing display...");
    lcd.init();
    lcd.setRotation(0);
    lcd.setBrightness(200);
    lcd.fillScreen(TFT_BLACK);
    Serial.println("Display initialized");

    // Initialize LVGL
    Serial.println("Initializing LVGL...");
    lv_init();

    // Allocate draw buffers in PSRAM
    buf1 = (lv_color_t *)heap_caps_malloc(DRAW_BUF_SIZE * sizeof(lv_color_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!buf1) {
        Serial.println("PSRAM alloc failed, using internal RAM");
        buf1 = (lv_color_t *)malloc(DRAW_BUF_SIZE * sizeof(lv_color_t));
    }

    if (!buf1) {
        Serial.println("Buffer allocation failed!");
        while(1) delay(100);
    }
    Serial.println("Buffer allocated");

    // Initialize LVGL draw buffer
    lv_disp_draw_buf_init(&draw_buf, buf1, nullptr, DRAW_BUF_SIZE);

    // Initialize display driver
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = 480;
    disp_drv.ver_res = 480;
    disp_drv.flush_cb = lvgl_flush_cb;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);
    Serial.println("Display driver registered");

    // Initialize touch input driver
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = lvgl_touch_cb;
    lv_indev_drv_register(&indev_drv);
    Serial.println("Touch driver registered");

    // Setup encoder pins
    pinMode(ENCODER_A, INPUT_PULLUP);
    pinMode(ENCODER_B, INPUT_PULLUP);
    pinMode(ENCODER_BTN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(ENCODER_A), encoder_isr, CHANGE);

    // Create UI
    setup_ui();
    update_status("Connecting WiFi...");
    lv_timer_handler();

    // Connect to WiFi
    Serial.println("Connecting WiFi...");
    WiFi.mode(WIFI_STA);
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
        Serial.print("Gateway: ");
        Serial.println(WiFi.gatewayIP());
        Serial.print("DNS: ");
        Serial.println(WiFi.dnsIP());
        Serial.printf("Backend URL: http://%s:%d/api/hal/status\n", api_host.c_str(), api_port);
        update_status("HAL 9000 Online");
    } else {
        Serial.println("\nWiFi connection failed!");
        update_status("Offline Mode");
    }

    // Start eye animation
    start_eye_animation();
    Serial.println("Setup complete!");
}

void loop() {
    lv_timer_handler();
    delay(5);

    // Poll backend status every 5 seconds to register ESP32 connection
    static unsigned long last_status_poll = 0;
    if (millis() - last_status_poll > 5000) {
        last_status_poll = millis();

        if (WiFi.status() == WL_CONNECTED) {
            HTTPClient http;
            String url = "http://" + api_host + ":" + String(api_port) + "/api/hal/status";

            if (!http.begin(url)) {
                Serial.println("HTTP begin failed!");
                return;
            }

            http.setTimeout(5000);  // Increased to 5 second timeout
            http.setReuse(false);   // Don't reuse connections
            int httpCode = http.GET();

            if (httpCode > 0) {
                // Success - backend received our connection
                static bool first_success = true;
                if (first_success) {
                    Serial.printf("Backend connected! HTTP %d\n", httpCode);
                    first_success = false;
                }
            } else {
                // Error codes: -1 = connection failed, -11 = timeout
                const char* errorStr = http.errorToString(httpCode).c_str();
                Serial.printf("Backend poll error: %d (%s) URL: %s\n", httpCode, errorStr, url.c_str());
            }

            http.end();
        } else {
            Serial.println("WiFi disconnected!");
        }
    }

    // Check encoder button
    static bool last_btn = HIGH;
    bool btn = digitalRead(ENCODER_BTN);
    if (btn == LOW && last_btn == HIGH) {
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
    lv_obj_set_style_bg_color(lv_scr_act(), lv_color_black(), 0);

    // Create HAL eye
    create_hal_eye();

    // Status label at bottom
    status_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(status_label, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_16, 0);
    lv_label_set_text(status_label, "Initializing...");
    lv_obj_align(status_label, LV_ALIGN_BOTTOM_MID, 0, -40);

    // Response label (hidden initially)
    response_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(response_label, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_text_font(response_label, &lv_font_montserrat_14, 0);
    lv_label_set_long_mode(response_label, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(response_label, 400);
    lv_label_set_text(response_label, "");
    lv_obj_align(response_label, LV_ALIGN_TOP_MID, 0, 40);
    lv_obj_add_flag(response_label, LV_OBJ_FLAG_HIDDEN);
}

void create_hal_eye() {
    // Outer glow ring (dark red)
    hal_eye_outer = lv_obj_create(lv_scr_act());
    lv_obj_set_size(hal_eye_outer, 280, 280);
    lv_obj_set_style_radius(hal_eye_outer, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(hal_eye_outer, lv_color_hex(0x400000), 0);
    lv_obj_set_style_border_width(hal_eye_outer, 0, 0);
    lv_obj_set_style_shadow_width(hal_eye_outer, 60, 0);
    lv_obj_set_style_shadow_color(hal_eye_outer, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_shadow_spread(hal_eye_outer, 20, 0);
    lv_obj_set_style_shadow_opa(hal_eye_outer, LV_OPA_70, 0);
    lv_obj_align(hal_eye_outer, LV_ALIGN_CENTER, 0, 0);
    lv_obj_clear_flag(hal_eye_outer, LV_OBJ_FLAG_SCROLLABLE);

    // Main eye circle (red)
    hal_eye_inner = lv_obj_create(lv_scr_act());
    lv_obj_set_size(hal_eye_inner, 200, 200);
    lv_obj_set_style_radius(hal_eye_inner, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(hal_eye_inner, lv_color_hex(0xCC0000), 0);
    lv_obj_set_style_border_width(hal_eye_inner, 4, 0);
    lv_obj_set_style_border_color(hal_eye_inner, lv_color_hex(0xFF0000), 0);
    lv_obj_set_style_shadow_width(hal_eye_inner, 30, 0);
    lv_obj_set_style_shadow_color(hal_eye_inner, lv_color_hex(0xFF0000), 0);
    lv_obj_align(hal_eye_inner, LV_ALIGN_CENTER, 0, 0);
    lv_obj_clear_flag(hal_eye_inner, LV_OBJ_FLAG_SCROLLABLE);

    // Center bright spot (yellow)
    hal_eye_center = lv_obj_create(lv_scr_act());
    lv_obj_set_size(hal_eye_center, 60, 60);
    lv_obj_set_style_radius(hal_eye_center, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(hal_eye_center, lv_color_hex(0xFFFF00), 0);
    lv_obj_set_style_border_width(hal_eye_center, 0, 0);
    lv_obj_set_style_shadow_width(hal_eye_center, 20, 0);
    lv_obj_set_style_shadow_color(hal_eye_center, lv_color_hex(0xFFFF00), 0);
    lv_obj_align(hal_eye_center, LV_ALIGN_CENTER, 0, 0);
    lv_obj_clear_flag(hal_eye_center, LV_OBJ_FLAG_SCROLLABLE);

    // Add touch event to eye
    lv_obj_add_flag(hal_eye_inner, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(hal_eye_inner, on_eye_touch, LV_EVENT_CLICKED, NULL);
}

void start_eye_animation() {
    lv_anim_init(&eye_pulse_anim);
    lv_anim_set_var(&eye_pulse_anim, hal_eye_outer);
    lv_anim_set_values(&eye_pulse_anim, 50, 80);
    lv_anim_set_time(&eye_pulse_anim, 2000);
    lv_anim_set_repeat_count(&eye_pulse_anim, LV_ANIM_REPEAT_INFINITE);
    lv_anim_set_playback_time(&eye_pulse_anim, 2000);
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

    JsonDocument doc;
    doc["message"] = message;
    JsonArray history = doc["history"].to<JsonArray>();

    String payload;
    serializeJson(doc, payload);

    int httpCode = http.POST(payload);

    if (httpCode > 0) {
        String response = http.getString();
        Serial.println("Response: " + response);

        JsonDocument respDoc;
        DeserializationError error = deserializeJson(respDoc, response);

        if (!error) {
            const char* hal_response = respDoc["response"];
            if (hal_response) {
                lv_obj_clear_flag(response_label, LV_OBJ_FLAG_HIDDEN);
                lv_label_set_text(response_label, hal_response);
                update_status("HAL 9000 Online");
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
