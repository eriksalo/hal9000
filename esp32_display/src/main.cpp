/*
 * HAL 9000 Display Interface
 * For VIEWE 2.1" Round Touch Knob Display (UEDX48480021-MD80ET)
 *
 * Features:
 * - Movie-accurate HAL 9000 eye with gradient rings and smooth pulsing
 * - State-based color shifts (idle, listening, speaking)
 * - Face display mode with red-filtered JPEG streaming from Pi
 */

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <esp_display_panel.hpp>
#include <lvgl.h>
#include <TJpg_Decoder.h>
#include "lvgl_v8_port.h"
#include "secrets.h"

using namespace esp_panel::drivers;
using namespace esp_panel::board;

// Display dimensions
#define SCREEN_WIDTH      480
#define SCREEN_HEIGHT     480
#define CENTER_X          240
#define CENTER_Y          240

// HAL eye parameters - movie accurate
#define EYE_OUTER_RADIUS    140
#define EYE_RING_1_RADIUS   130
#define EYE_RING_2_RADIUS   118
#define EYE_RING_3_RADIUS   105
#define EYE_RING_4_RADIUS   90
#define EYE_INNER_RADIUS    75
#define EYE_CENTER_RADIUS   30
#define EYE_HIGHLIGHT_RADIUS 13
#define EYE_NUM_RINGS       22
#define EYE_R_EDGE          150
#define EYE_R_CORE          30

// Display modes
enum DisplayMode {
    MODE_EYE,
    MODE_FACE
};

// LVGL objects for HAL eye layers (outer to inner)
static lv_obj_t *outer_glow = NULL;
static lv_obj_t *rings[EYE_NUM_RINGS] = {NULL};
static lv_obj_t *center_yellow = NULL;
static lv_obj_t *center_highlight = NULL;
static lv_obj_t *center_glint = NULL;
static lv_obj_t *status_label = NULL;

// Face display objects
static lv_obj_t *face_canvas = NULL;
static lv_color_t *face_buffer = NULL;

// Animation state
static unsigned long last_display_check = 0;
static unsigned long last_frame_fetch = 0;

// HAL state from backend
static String hal_state = "idle";
static bool hal_listening = false;
static bool hal_speaking = false;
static DisplayMode current_mode = MODE_EYE;
static String current_person = "";

// API settings from secrets.h
String api_host = HAL_API_HOST;
int api_port = HAL_API_PORT;

// JPEG decoding variables
static bool jpeg_decode_success = false;

// Forward declarations
void create_hal_eye(void);
void create_face_display(void);
void update_hal_eye(lv_timer_t *timer);
void check_display_state(void);
void fetch_face_frame(void);
void show_eye_mode(void);
void show_face_mode(void);
bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap);

// JPEG decoder callback - draws to LVGL canvas
bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
    if (face_canvas == NULL || face_buffer == NULL) return false;

    // Copy decoded pixels to canvas buffer
    for (int j = 0; j < h; j++) {
        for (int i = 0; i < w; i++) {
            int px = x + i;
            int py = y + j;
            if (px < SCREEN_WIDTH && py < SCREEN_HEIGHT) {
                face_buffer[py * SCREEN_WIDTH + px].full = bitmap[j * w + i];
            }
        }
    }
    return true;
}

void setup()
{
    Serial.begin(115200);
    delay(2000);
    Serial.println("\n\n========================================");
    Serial.println("HAL 9000 Display Starting...");
    Serial.println("========================================");

    // Initialize board
    Serial.println("Creating board object...");
    Board *board = new Board();
    Serial.println("Board created, calling init...");
    if (!board->init()) {
        Serial.println("ERROR: Board init failed!");
    }
    Serial.println("Board init done");

#if LVGL_PORT_AVOID_TEARING_MODE
    auto lcd = board->getLCD();
    lcd->configFrameBufferNumber(LVGL_PORT_DISP_BUFFER_NUM);
#if ESP_PANEL_DRIVERS_BUS_ENABLE_RGB && CONFIG_IDF_TARGET_ESP32S3
    auto lcd_bus = lcd->getBus();
    if (lcd_bus->getBasicAttributes().type == ESP_PANEL_BUS_TYPE_RGB) {
        static_cast<BusRGB *>(lcd_bus)->configRGB_BounceBufferSize(lcd->getFrameWidth() * 10);
    }
#endif
#endif
    Serial.println("Calling board->begin()...");
    if (!board->begin()) {
        Serial.println("ERROR: board->begin() failed!");
    }
    Serial.println("Board started successfully");

    // Initialize LVGL
    Serial.println("Initializing LVGL...");
    lvgl_port_init(board->getLCD(), board->getTouch());
    Serial.println("LVGL initialized");

    // Initialize TJpg_Decoder
    TJpgDec.setJpgScale(1);
    TJpgDec.setSwapBytes(true);
    TJpgDec.setCallback(tft_output);

    // Create UI elements
    Serial.println("Creating HAL 9000 eye");
    lvgl_port_lock(-1);
    create_hal_eye();
    create_face_display();
    lvgl_port_unlock();

    // Connect to WiFi
    Serial.println("Connecting to WiFi...");
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int wifi_attempts = 0;
    while (WiFi.status() != WL_CONNECTED && wifi_attempts < 30) {
        delay(500);
        Serial.print(".");
        wifi_attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi connected!");
        Serial.print("IP: ");
        Serial.println(WiFi.localIP());

        // If the backend host is an mDNS name (e.g. "hal9000.local"), resolve it
        // to the Pi's current IP so the display keeps working across DHCP changes.
        // Requires avahi-daemon running on the Pi. Falls back to the name as-is.
        if (api_host.endsWith(".local")) {
            String mdnsName = api_host.substring(0, api_host.length() - 6); // strip ".local"
            MDNS.begin("hal-display");
            IPAddress halIP;
            for (int attempt = 0; attempt < 10; attempt++) {
                halIP = MDNS.queryHost(mdnsName, 2000);
                if (halIP != IPAddress(0, 0, 0, 0)) break;
                Serial.printf("Resolving %s.local (attempt %d)...\n", mdnsName.c_str(), attempt + 1);
                delay(500);
            }
            if (halIP != IPAddress(0, 0, 0, 0)) {
                api_host = halIP.toString();
                Serial.printf("Resolved HAL to %s\n", api_host.c_str());
            } else {
                Serial.println("mDNS resolution failed; using configured host as-is");
            }
        }
        Serial.printf("Backend URL: http://%s:%d/api/hal/display\n", api_host.c_str(), api_port);

        lvgl_port_lock(-1);
        lv_label_set_text(status_label, "HAL 9000 Online");
        lvgl_port_unlock();
    } else {
        Serial.println("\nWiFi failed!");
        lvgl_port_lock(-1);
        lv_label_set_text(status_label, "Offline Mode");
        lvgl_port_unlock();
    }

    Serial.println("Setup complete!");
}

void loop()
{
    unsigned long now = millis();

    // Check display state every 1 second
    if (now - last_display_check >= 1000) {
        last_display_check = now;
        check_display_state();
    }

    // Fetch face frame more frequently when in face mode
    if (current_mode == MODE_FACE && now - last_frame_fetch >= 200) {
        last_frame_fetch = now;
        fetch_face_frame();
    }

    delay(10);
}

void create_hal_eye(void)
{
    // Set black background
    lv_obj_set_style_bg_color(lv_scr_act(), lv_color_black(), 0);

    // Create outer glow circle (pulsing, darkest)
    outer_glow = lv_obj_create(lv_scr_act());
    lv_obj_remove_style_all(outer_glow);
    lv_obj_set_size(outer_glow, EYE_OUTER_RADIUS * 2 + 30, EYE_OUTER_RADIUS * 2 + 30);
    lv_obj_align(outer_glow, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_bg_color(outer_glow, lv_color_make(40, 0, 0), 0);
    lv_obj_set_style_bg_opa(outer_glow, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(outer_glow, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(outer_glow, 0, 0);

    // Lens: many concentric circles forming a smooth radial gradient (outer -> inner).
    for (int i = 0; i < EYE_NUM_RINGS; i++) {
        float t = (float)i / (EYE_NUM_RINGS - 1);              // 0 = edge, 1 = inner
        int radius = (int)(EYE_R_EDGE - (EYE_R_EDGE - EYE_R_CORE) * t);
        rings[i] = lv_obj_create(lv_scr_act());
        lv_obj_remove_style_all(rings[i]);
        lv_obj_set_size(rings[i], radius * 2, radius * 2);
        lv_obj_align(rings[i], LV_ALIGN_CENTER, 0, 0);
        lv_obj_set_style_bg_opa(rings[i], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(rings[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(rings[i], 0, 0);
    }

    // Gold halo at the center of the lens
    center_yellow = lv_obj_create(lv_scr_act());
    lv_obj_remove_style_all(center_yellow);
    lv_obj_set_size(center_yellow, EYE_CENTER_RADIUS * 2, EYE_CENTER_RADIUS * 2);
    lv_obj_align(center_yellow, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_bg_color(center_yellow, lv_color_make(255, 205, 70), 0);
    lv_obj_set_style_bg_opa(center_yellow, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(center_yellow, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(center_yellow, 0, 0);

    // White-hot core
    center_highlight = lv_obj_create(lv_scr_act());
    lv_obj_remove_style_all(center_highlight);
    lv_obj_set_size(center_highlight, EYE_HIGHLIGHT_RADIUS * 2, EYE_HIGHLIGHT_RADIUS * 2);
    lv_obj_align(center_highlight, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_bg_color(center_highlight, lv_color_make(255, 250, 235), 0);
    lv_obj_set_style_bg_opa(center_highlight, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(center_highlight, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(center_highlight, 0, 0);

    // Small specular glint, offset up-left (gives the lens depth)
    center_glint = lv_obj_create(lv_scr_act());
    lv_obj_remove_style_all(center_glint);
    lv_obj_set_size(center_glint, 11, 11);
    lv_obj_align(center_glint, LV_ALIGN_CENTER, -9, -10);
    lv_obj_set_style_bg_color(center_glint, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(center_glint, LV_OPA_80, 0);
    lv_obj_set_style_radius(center_glint, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(center_glint, 0, 0);

    // Create status label
    status_label = lv_label_create(lv_scr_act());
    lv_label_set_text(status_label, "Initializing...");
    lv_obj_set_style_text_color(status_label, lv_color_make(200, 0, 0), 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_16, 0);
    lv_obj_align(status_label, LV_ALIGN_BOTTOM_MID, 0, -30);

    // Create animation timer
    lv_timer_create(update_hal_eye, 33, NULL);  // ~30fps
}

void create_face_display(void)
{
    // Allocate face buffer in PSRAM
    face_buffer = (lv_color_t *)heap_caps_malloc(SCREEN_WIDTH * SCREEN_HEIGHT * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
    if (face_buffer == NULL) {
        Serial.println("ERROR: Failed to allocate face buffer in PSRAM!");
        return;
    }

    // Create canvas for face display
    face_canvas = lv_canvas_create(lv_scr_act());
    lv_canvas_set_buffer(face_canvas, face_buffer, SCREEN_WIDTH, SCREEN_HEIGHT, LV_IMG_CF_TRUE_COLOR);
    lv_obj_align(face_canvas, LV_ALIGN_CENTER, 0, 0);

    // Initially hidden
    lv_obj_add_flag(face_canvas, LV_OBJ_FLAG_HIDDEN);

    // Fill with black initially
    lv_canvas_fill_bg(face_canvas, lv_color_black(), LV_OPA_COVER);
}

void update_hal_eye(lv_timer_t *timer)
{
    // Skip animation if in face mode
    if (current_mode == MODE_FACE) return;

    // Sinusoidal pulse calculation
    float pulse_speed = 0.002f;  // Normal idle speed
    if (hal_listening) {
        pulse_speed = 0.006f;  // Faster when listening
    } else if (hal_speaking) {
        pulse_speed = 0.004f;  // Medium when speaking
    }

    // Smooth sinusoidal pulse (0.0 to 1.0)
    float pulse = (sin(millis() * pulse_speed) * 0.5f) + 0.5f;

    // Base colors based on state
    uint8_t base_r, base_g;
    if (hal_listening) {
        // Bright red when listening
        base_r = 255;
        base_g = 0;
    } else if (hal_speaking) {
        // Orange-red when speaking
        base_r = 255;
        base_g = 51;  // #FF3300
    } else {
        // Deep red when idle (#CC0000)
        base_r = 204;
        base_g = 0;
    }

    // Apply pulse to colors (vary brightness)
    float brightness = 0.7f + (pulse * 0.3f);

    // Update outer glow size based on pulse
    int pulse_offset = (int)(pulse * 20);
    int glow_size = (EYE_OUTER_RADIUS * 2) + 30 + pulse_offset;
    lv_obj_set_size(outer_glow, glow_size, glow_size);
    lv_obj_align(outer_glow, LV_ALIGN_CENTER, 0, 0);

    // Update glow color
    lv_obj_set_style_bg_color(outer_glow, lv_color_make((uint8_t)(40 * brightness), 0, 0), 0);

    // Hot inner color by state (HAL stays in the red family; movie-accurate).
    float hotR, hotG;
    if (hal_listening)      { hotR = 255; hotG = 40; }   // bright, alert
    else if (hal_speaking)  { hotR = 255; hotG = 95; }   // warm orange
    else                    { hotR = 235; hotG = 24; }   // deep idle red

    // Colour each lens ring along a smooth radial falloff (rim dark -> core hot).
    for (int i = 0; i < EYE_NUM_RINGS; i++) {
        float t = (float)i / (EYE_NUM_RINGS - 1);        // 0 edge -> 1 inner
        float f = (0.10f + 0.90f * powf(t, 1.6f)) * brightness;
        uint8_t r = (uint8_t)fminf(255.0f, hotR * f);
        uint8_t g = (uint8_t)fminf(255.0f, hotG * f);
        lv_obj_set_style_bg_color(rings[i], lv_color_make(r, g, 0), 0);
    }

    // Gold halo + white-hot core breathe gently with the pulse.
    uint8_t halo_g = 190 + (uint8_t)(pulse * 45);
    lv_obj_set_style_bg_color(center_yellow, lv_color_make(255, halo_g, (uint8_t)(55 + pulse * 35)), 0);
    lv_obj_set_style_bg_opa(center_highlight, (lv_opa_t)(220 + (int)(pulse * 35)), 0);
}

void check_display_state(void)
{
    if (WiFi.status() != WL_CONNECTED) {
        return;
    }

    HTTPClient http;
    String url = "http://" + api_host + ":" + String(api_port) + "/api/hal/display";

    http.begin(url);
    http.setTimeout(2000);

    int httpCode = http.GET();

    if (httpCode == 200) {
        String response = http.getString();

        JsonDocument doc;
        if (!deserializeJson(doc, response)) {
            // Get mode
            const char* mode = doc["mode"];
            DisplayMode new_mode = (strcmp(mode, "face") == 0) ? MODE_FACE : MODE_EYE;

            // Get state
            if (doc["state"].is<const char*>()) {
                hal_state = doc["state"].as<String>();
                hal_listening = hal_state.indexOf("awaiting") >= 0 ||
                               hal_state.indexOf("listening") >= 0;
                hal_speaking = hal_state.indexOf("asking") >= 0 ||
                              hal_state.indexOf("confirming") >= 0 ||
                              hal_state.indexOf("speaking") >= 0;
            }

            // Get person name
            if (doc["person"].is<const char*>()) {
                current_person = doc["person"].as<String>();
            } else {
                current_person = "";
            }

            // Switch modes if needed
            if (new_mode != current_mode) {
                current_mode = new_mode;
                lvgl_port_lock(-1);
                if (current_mode == MODE_FACE) {
                    show_face_mode();
                } else {
                    show_eye_mode();
                }
                lvgl_port_unlock();
            }

            // Update status label
            lvgl_port_lock(-1);
            if (current_mode == MODE_FACE && current_person.length() > 0) {
                lv_label_set_text(status_label, current_person.c_str());
            } else if (hal_listening) {
                lv_label_set_text(status_label, "Listening...");
            } else if (hal_speaking) {
                lv_label_set_text(status_label, "Speaking...");
            } else {
                lv_label_set_text(status_label, "HAL 9000 Online");
            }
            lvgl_port_unlock();
        }
    } else if (httpCode < 0) {
        Serial.println("Display check failed: " + String(httpCode));
    }

    http.end();
}

void show_eye_mode(void)
{
    // Show eye objects
    lv_obj_clear_flag(outer_glow, LV_OBJ_FLAG_HIDDEN);
    for (int i = 0; i < EYE_NUM_RINGS; i++) lv_obj_clear_flag(rings[i], LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(center_yellow, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(center_highlight, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(center_glint, LV_OBJ_FLAG_HIDDEN);

    // Hide face canvas
    if (face_canvas) {
        lv_obj_add_flag(face_canvas, LV_OBJ_FLAG_HIDDEN);
    }

    Serial.println("Switched to EYE mode");
}

void show_face_mode(void)
{
    // Hide eye objects
    lv_obj_add_flag(outer_glow, LV_OBJ_FLAG_HIDDEN);
    for (int i = 0; i < EYE_NUM_RINGS; i++) lv_obj_add_flag(rings[i], LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(center_yellow, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(center_highlight, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(center_glint, LV_OBJ_FLAG_HIDDEN);

    // Show face canvas
    if (face_canvas) {
        lv_obj_clear_flag(face_canvas, LV_OBJ_FLAG_HIDDEN);
    }

    Serial.println("Switched to FACE mode");
}

void fetch_face_frame(void)
{
    if (WiFi.status() != WL_CONNECTED || face_buffer == NULL) {
        return;
    }

    HTTPClient http;
    String url = "http://" + api_host + ":" + String(api_port) + "/api/hal/face_frame?red=true&size=480";

    http.begin(url);
    http.setTimeout(3000);

    int httpCode = http.GET();

    if (httpCode == 200) {
        int len = http.getSize();
        if (len > 0 && len < 200000) {  // Sanity check
            uint8_t *jpeg_buffer = (uint8_t *)heap_caps_malloc(len, MALLOC_CAP_SPIRAM);
            if (jpeg_buffer) {
                WiFiClient *stream = http.getStreamPtr();
                int bytesRead = stream->readBytes(jpeg_buffer, len);

                if (bytesRead == len) {
                    // Decode JPEG to canvas
                    lvgl_port_lock(-1);
                    jpeg_decode_success = (TJpgDec.drawJpg(0, 0, jpeg_buffer, len) == 1);
                    if (jpeg_decode_success && face_canvas) {
                        lv_obj_invalidate(face_canvas);
                    }
                    lvgl_port_unlock();
                }

                heap_caps_free(jpeg_buffer);
            }
        }
    } else if (httpCode < 0) {
        Serial.println("Face frame fetch failed: " + String(httpCode));
    }

    http.end();
}
