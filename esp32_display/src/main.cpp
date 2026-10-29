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

// HAL eye renderer - procedural radial framebuffer (smooth, high-res, dithered).
// The eye is drawn per-pixel into a full-screen canvas so it fills the round display.
#define EYE_CANVAS_SIZE   480          // framebuffer is EYE_CANVAS_SIZE^2 (full screen)
#define EYE_CANVAS_CENTER 240          // center of that canvas
#define EYE_PROFILE_MAX   245          // radial color profile covers r in [0, EYE_PROFILE_MAX)
#define EYE_DIST_OUTSIDE  255          // LUT sentinel: pixel lies outside the eye -> black

// Nominal eye geometry (radius in pixels from the canvas center). Sized so the glow
// reaches the edge of the 480px round display.
#define EYE_R_CORE   18.0f             // white-hot core (dilates with the animation)
#define EYE_R_HALO   46.0f             // gold halo
#define EYE_R_LENS   196.0f            // outer edge of the solid lens
#define EYE_R_GLOW   236.0f            // soft glow fades to black by here (near the rim)

// On-screen content rotation to compensate for a physically rotated mount.
// Positive = clockwise (as the viewer sees it). The eye is radially symmetric so
// only the status text is visibly affected; flip the sign if the mount tilts the
// other way. 0 = no rotation.
#define UI_ROTATION_DEG   30.0f
#define UI_LABEL_RADIUS   214.0f       // distance of the status text from center (near the rim)

// Display modes
enum DisplayMode {
    MODE_EYE,
    MODE_FACE
};

// Which animation the eye is currently playing.
enum EyeState {
    EYE_IDLE,
    EYE_LISTENING,
    EYE_THINKING,
    EYE_SPEAKING
};

// Procedural eye framebuffer + distance LUT (both in PSRAM)
static lv_obj_t  *eye_canvas = NULL;
static lv_color_t *eye_buffer = NULL;   // EYE_CANVAS_SIZE^2 pixels
static uint8_t    *eye_dist = NULL;     // per-pixel distance from center (EYE_DIST_OUTSIDE = black)
static lv_obj_t  *status_label = NULL;

// Animation state (set by the network poll, read by the LVGL render timer)
static EyeState eye_state = EYE_IDLE;
static EyeState eye_state_prev = EYE_IDLE;
static unsigned long eye_accent_t0 = 0; // when the state last changed -> drives the accent ring

// Tunables for one eye "animation". The renderer eases the live values toward the
// target for the active state, so state changes morph smoothly instead of snapping.
struct EyeParams {
    float hotR, hotG;        // lens "hot" color
    float coreR;             // base core radius
    float breatheSpeed, breatheAmp;
    float waveAmp, waveFreq, waveSpeed, waveDir;  // ripple: dir +1 inward, -1 outward
    float glowLevel, jitter, glintSpeed;
};
// Live (eased) parameters; initialized to the idle animation.
static EyeParams eye_cur = {230.f, 18.f, 13.f, 0.0012f, 0.14f, 0.06f, 1.3f, 0.0016f, 1.f, 0.92f, 0.f, 0.0006f};

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
    // Black screen background; the eye lives inside a centered canvas.
    lv_obj_set_style_bg_color(lv_scr_act(), lv_color_black(), 0);

    // Allocate the eye framebuffer and a distance-from-center LUT in PSRAM.
    size_t npx = (size_t)EYE_CANVAS_SIZE * EYE_CANVAS_SIZE;
    eye_buffer = (lv_color_t *)heap_caps_malloc(npx * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
    eye_dist   = (uint8_t *)heap_caps_malloc(npx, MALLOC_CAP_SPIRAM);
    if (eye_buffer == NULL || eye_dist == NULL) {
        Serial.println("ERROR: Failed to allocate eye buffers in PSRAM!");
        return;
    }

    // Precompute each pixel's rounded distance from the center. Pixels beyond the
    // glow radius are tagged so the profile renders them black. This turns the
    // per-frame fill into one byte-read + one table lookup per pixel.
    for (int y = 0; y < EYE_CANVAS_SIZE; y++) {
        int dy = y - EYE_CANVAS_CENTER;
        int dy2 = dy * dy;
        uint8_t *row = eye_dist + (size_t)y * EYE_CANVAS_SIZE;
        for (int x = 0; x < EYE_CANVAS_SIZE; x++) {
            int dx = x - EYE_CANVAS_CENTER;
            int d = (int)(sqrtf((float)(dx * dx + dy2)) + 0.5f);
            row[x] = (d < EYE_PROFILE_MAX) ? (uint8_t)d : EYE_DIST_OUTSIDE;
        }
    }

    // Canvas centered on the screen.
    eye_canvas = lv_canvas_create(lv_scr_act());
    lv_canvas_set_buffer(eye_canvas, eye_buffer, EYE_CANVAS_SIZE, EYE_CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);
    lv_obj_align(eye_canvas, LV_ALIGN_CENTER, 0, 0);
    lv_canvas_fill_bg(eye_canvas, lv_color_black(), LV_OPA_COVER);

    // Status label, placed at the rotated "bottom" and tilted to match the mount.
    // Fixed width + centered text keeps the rotation pivot stable as the text changes.
    status_label = lv_label_create(lv_scr_act());
    lv_obj_set_width(status_label, 200);
    lv_obj_set_style_text_align(status_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text(status_label, "Initializing...");
    lv_obj_set_style_text_color(status_label, lv_color_make(255, 60, 40), 0);
    lv_obj_set_style_text_font(status_label, &lv_font_montserrat_16, 0);
    // Dark rounded backing so the text reads over the eye's glow.
    lv_obj_set_style_bg_color(status_label, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(status_label, LV_OPA_50, 0);
    lv_obj_set_style_pad_ver(status_label, 3, 0);
    lv_obj_set_style_radius(status_label, 8, 0);

    float ui_rad = UI_ROTATION_DEG * 0.01745329f;   // degrees -> radians
    int label_dx = (int)(-UI_LABEL_RADIUS * sinf(ui_rad));
    int label_dy = (int)( UI_LABEL_RADIUS * cosf(ui_rad));
    lv_obj_align(status_label, LV_ALIGN_CENTER, label_dx, label_dy);
    lv_obj_set_style_transform_pivot_x(status_label, 100, 0);  // half of the fixed width
    lv_obj_set_style_transform_pivot_y(status_label, 10, 0);
    lv_obj_set_style_transform_angle(status_label, (int)(UI_ROTATION_DEG * 10.0f), 0);  // 0.1deg units, CW

    // Procedural animation timer (~30fps).
    lv_timer_create(update_hal_eye, 33, NULL);
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
    if (current_mode == MODE_FACE || eye_buffer == NULL) return;

    float ms = (float)millis();

    // --- Target parameters for the active state's animation -------------------
    // Fields: hotR, hotG, coreR, breatheSpeed, breatheAmp,
    //         waveAmp, waveFreq, waveSpeed, waveDir, glowLevel, jitter, glintSpeed
    EyeParams tgt;
    switch (eye_state) {
    case EYE_LISTENING:   // alert, "receiving" - bright red, ripples expand OUTWARD
        tgt = {255.f,  60.f, 15.f, 0.0022f, 0.12f, 0.16f, 2.2f, 0.0060f, -1.f, 1.05f, 0.00f, 0.0014f};
        break;
    case EYE_THINKING:    // contemplative - gold, bands march INWARD, glint sweeps the lens
        tgt = {255.f, 150.f, 14.f, 0.0016f, 0.10f, 0.13f, 3.0f, 0.0050f,  1.f, 1.00f, 0.00f, 0.0032f};
        break;
    case EYE_SPEAKING:    // vocalizing - warm amber, brightness jitters like speech
        tgt = {255.f, 105.f, 16.f, 0.0030f, 0.10f, 0.18f, 2.0f, 0.0100f,  1.f, 1.05f, 0.38f, 0.0012f};
        break;
    default:              // idle - calm, deep red, nearly still
        tgt = {230.f,  18.f, 13.f, 0.0012f, 0.14f, 0.06f, 1.3f, 0.0016f,  1.f, 0.92f, 0.00f, 0.0006f};
        break;
    }

    // Ease the live parameters toward the target so states morph, not snap.
    EyeParams *c = &eye_cur;
    const float k = 0.08f;
    c->hotR += (tgt.hotR - c->hotR) * k;
    c->hotG += (tgt.hotG - c->hotG) * k;
    c->coreR += (tgt.coreR - c->coreR) * k;
    c->breatheSpeed += (tgt.breatheSpeed - c->breatheSpeed) * k;
    c->breatheAmp += (tgt.breatheAmp - c->breatheAmp) * k;
    c->waveAmp += (tgt.waveAmp - c->waveAmp) * k;
    c->waveFreq += (tgt.waveFreq - c->waveFreq) * k;
    c->waveSpeed += (tgt.waveSpeed - c->waveSpeed) * k;
    c->waveDir += (tgt.waveDir - c->waveDir) * k;
    c->glowLevel += (tgt.glowLevel - c->glowLevel) * k;
    c->jitter += (tgt.jitter - c->jitter) * k;
    c->glintSpeed += (tgt.glintSpeed - c->glintSpeed) * k;

    // --- Global brightness envelope ------------------------------------------
    float breathe = 0.5f + 0.5f * sinf(ms * c->breatheSpeed);
    float bright = (1.0f - c->breatheAmp) + c->breatheAmp * breathe;

    // Speech-like jitter while speaking: an irregular, livelier envelope.
    if (c->jitter > 0.01f) {
        float env = 0.5f + 0.5f * sinf(ms * 0.019f);
        env *= 0.6f + 0.4f * (0.5f + 0.5f * sinf(ms * 0.043f + 1.0f));
        bright = bright * (1.0f - c->jitter) + (0.72f + 0.6f * env) * c->jitter;
    }

    // Occasional brief flicker so HAL never feels static.
    float flick = sinf(ms * 0.013f) * sinf(ms * 0.07f);
    if (flick > 0.93f) bright *= 0.82f;

    // Accent ring: a bright band that expands and fades whenever the state changes.
    float acc_age = ms - (float)eye_accent_t0;
    float acc_r = acc_age * 0.42f;                                   // travels outward (px)
    float acc_amp = (acc_age < 1100.f) ? expf(-acc_age / 320.f) * 0.9f : 0.0f;

    // White-hot core dilates on its own slow rhythm.
    float coreShim = 0.5f + 0.5f * sinf(ms * 0.006f);
    float coreR = c->coreR + coreShim * 3.0f;

    // --- Build the radial color profile (one entry per pixel-radius) ----------
    // Kept at full 8-bit precision; dithered down to RGB565 during the fill so the
    // smooth gradient doesn't show concentric banding on the panel.
    static uint8_t profR[256], profG[256], profB[256];
    float hotR = c->hotR, hotG = c->hotG;
    for (int r = 0; r < EYE_PROFILE_MAX; r++) {
        float fr = (float)r;
        float R = 0.f, G = 0.f, B = 0.f;

        if (fr < coreR) {                         // white-hot core, warms to the halo at its edge
            // At t=1 this equals the halo's start color (255,210,110)*bright, so the
            // core blends seamlessly into the halo with no ring.
            float t = fr / coreR;
            R = 255.f * bright;
            G = (250.f - 40.f * t) * bright;
            B = (235.f - 125.f * t) * bright;
        } else if (fr < EYE_R_HALO) {             // gold halo: white -> lens hot color
            float t = (fr - coreR) / (EYE_R_HALO - coreR);
            R = (255.f * (1.f - t) + hotR * t) * bright;
            G = (210.f * (1.f - t) + hotG * t) * bright;
            B = (110.f * (1.f - t)) * bright;
        } else if (fr < EYE_R_LENS) {             // main lens: radial gradient + ripple
            float t = (fr - EYE_R_HALO) / (EYE_R_LENS - EYE_R_HALO);   // 0 inner -> 1 outer
            float radial = 1.0f - 0.72f * t;                           // brighter toward center
            float phase = c->waveFreq * t * 6.2832f + c->waveDir * ms * c->waveSpeed;
            float f = radial * bright * (1.0f + c->waveAmp * sinf(phase));
            if (acc_amp > 0.002f) {               // expanding accent band
                float d = fr - acc_r;
                f += acc_amp * expf(-(d * d) / 180.f);
            }
            if (f < 0.f) f = 0.f;
            R = hotR * f;
            G = hotG * f;
        } else if (fr < EYE_R_GLOW) {             // soft outer glow, continuous with the lens edge
            // Start exactly where the lens leaves off (its radial intensity at t=1 is
            // 1 - 0.72 = 0.28) so there is no brightness step/ring at the boundary.
            float t = (fr - EYE_R_LENS) / (EYE_R_GLOW - EYE_R_LENS);
            float fall = (1.0f - t) * (1.0f - t);
            float f = 0.28f * fall * bright * c->glowLevel;
            R = hotR * f;
            G = hotG * f * 0.7f;
        }

        if (R > 255.f) R = 255.f; if (R < 0.f) R = 0.f;
        if (G > 255.f) G = 255.f; if (G < 0.f) G = 0.f;
        if (B > 255.f) B = 255.f; if (B < 0.f) B = 0.f;
        profR[r] = (uint8_t)R; profG[r] = (uint8_t)G; profB[r] = (uint8_t)B;
    }
    for (int r = EYE_PROFILE_MAX; r < 256; r++) { profR[r] = profG[r] = profB[r] = 0; }

    // --- Fill the framebuffer, dithering 8-bit color down to RGB565 ----------
    // An 8x8 ordered (Bayer) dither spreads the quantization error across neighbouring
    // pixels with 64 fine gradations, turning hard colour steps into a smooth gradient.
    // Dither amplitude is tuned slightly above each channel's quantization step
    // (red/blue: 8, green: 4) so no residual contour rings survive.
    static const uint8_t bayer8[64] = {
         0, 32,  8, 40,  2, 34, 10, 42,
        48, 16, 56, 24, 50, 18, 58, 26,
        12, 44,  4, 36, 14, 46,  6, 38,
        60, 28, 52, 20, 62, 30, 54, 22,
         3, 35, 11, 43,  1, 33,  9, 41,
        51, 19, 59, 27, 49, 17, 57, 25,
        15, 47,  7, 39, 13, 45,  5, 37,
        63, 31, 55, 23, 61, 29, 53, 21,
    };
    lv_color_t *fb = eye_buffer;
    uint8_t *dl = eye_dist;
    for (int y = 0; y < EYE_CANVAS_SIZE; y++) {
        const uint8_t *brow = &bayer8[(y & 7) << 3];
        uint8_t *drow = dl + (size_t)y * EYE_CANVAS_SIZE;
        lv_color_t *frow = fb + (size_t)y * EYE_CANVAS_SIZE;
        for (int x = 0; x < EYE_CANVAS_SIZE; x++) {
            uint8_t d = drow[x];
            if (d >= EYE_PROFILE_MAX) { frow[x] = lv_color_black(); continue; }
            int bt = (int)brow[x & 7] - 32;         // -32..+31
            int r = profR[d] + ((bt * 10) >> 6);    // red step ~8 (5-bit channel)
            int g = profG[d] + ((bt *  6) >> 6);    // green step ~4 (6-bit channel)
            int b = profB[d] + ((bt * 10) >> 6);
            if (r > 255) r = 255; else if (r < 0) r = 0;
            if (g > 255) g = 255; else if (g < 0) g = 0;
            if (b > 255) b = 255; else if (b < 0) b = 0;
            frow[x] = lv_color_make((uint8_t)r, (uint8_t)g, (uint8_t)b);
        }
    }

    // --- Specular glint: a bright highlight that orbits the lens -------------
    // During "thinking" it sweeps the mid-lens like a scanning beam; otherwise it
    // hovers near the core like a reflection on glass.
    float ga = ms * c->glintSpeed;
    float orbitR = (eye_state == EYE_THINKING) ? 125.0f : (EYE_R_HALO * 0.55f);
    int gcx = EYE_CANVAS_CENTER + (int)(cosf(ga) * orbitR) - 2;
    int gcy = EYE_CANVAS_CENTER + (int)(sinf(ga) * orbitR) - 3;
    const int gr = 7;
    for (int dy = -gr; dy <= gr; dy++) {
        int py = gcy + dy;
        if (py < 0 || py >= EYE_CANVAS_SIZE) continue;
        for (int dx = -gr; dx <= gr; dx++) {
            int px = gcx + dx;
            if (px < 0 || px >= EYE_CANVAS_SIZE) continue;
            float d2 = (float)(dx * dx + dy * dy);
            if (d2 > (float)(gr * gr)) continue;
            float a = 1.0f - sqrtf(d2) / (float)gr;
            a *= a;
            if (a < 0.12f) continue;
            fb[(size_t)py * EYE_CANVAS_SIZE + px] =
                lv_color_make(255, (uint8_t)(210 + 45 * a), (uint8_t)(150 + 95 * a));
        }
    }

    lv_obj_invalidate(eye_canvas);
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

            // Get state -> which eye animation to play
            if (doc["state"].is<const char*>()) {
                hal_state = doc["state"].as<String>();
                EyeState ns;
                if (hal_state == "speaking")       ns = EYE_SPEAKING;
                else if (hal_state == "thinking")  ns = EYE_THINKING;
                else if (hal_state == "listening") ns = EYE_LISTENING;
                else                               ns = EYE_IDLE;   // idle / offline
                // Legacy substring fallback for older backends.
                if (ns == EYE_IDLE) {
                    if (hal_state.indexOf("awaiting") >= 0 || hal_state.indexOf("listening") >= 0)
                        ns = EYE_LISTENING;
                    else if (hal_state.indexOf("asking") >= 0 || hal_state.indexOf("confirming") >= 0 ||
                             hal_state.indexOf("speaking") >= 0)
                        ns = EYE_SPEAKING;
                }
                if (ns != eye_state) {
                    eye_state_prev = eye_state;
                    eye_state = ns;
                    eye_accent_t0 = millis();   // trigger the transition accent ring
                }
                hal_listening = (eye_state == EYE_LISTENING);
                hal_speaking  = (eye_state == EYE_SPEAKING);
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
            } else if (eye_state == EYE_LISTENING) {
                lv_label_set_text(status_label, "Listening...");
            } else if (eye_state == EYE_THINKING) {
                lv_label_set_text(status_label, "Thinking...");
            } else if (eye_state == EYE_SPEAKING) {
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
    if (eye_canvas) lv_obj_clear_flag(eye_canvas, LV_OBJ_FLAG_HIDDEN);
    if (face_canvas) lv_obj_add_flag(face_canvas, LV_OBJ_FLAG_HIDDEN);
    Serial.println("Switched to EYE mode");
}

void show_face_mode(void)
{
    if (eye_canvas) lv_obj_add_flag(eye_canvas, LV_OBJ_FLAG_HIDDEN);
    if (face_canvas) lv_obj_clear_flag(face_canvas, LV_OBJ_FLAG_HIDDEN);
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
