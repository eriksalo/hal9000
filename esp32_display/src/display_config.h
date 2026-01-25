/**
 * Display Configuration for VIEWE 2.1" Round Display
 * UEDX48480021-MD80ESP32 with ST7701S driver
 */

#ifndef DISPLAY_CONFIG_H
#define DISPLAY_CONFIG_H

#define LGFX_USE_V1
#include <LovyanGFX.hpp>
#include <lgfx/v1/platforms/esp32s3/Panel_RGB.hpp>
#include <lgfx/v1/platforms/esp32s3/Bus_RGB.hpp>

// Pin definitions for VIEWE 2.1" Round Display
#define TFT_BL      38  // Backlight
#define TFT_RST     -1  // Reset (not used, directly connected to 3.3V)
#define TFT_CS      39  // Chip select
#define TFT_SCLK    48  // SPI Clock
#define TFT_MOSI    47  // SPI MOSI

// RGB interface pins
#define TFT_DE      18
#define TFT_VSYNC   17
#define TFT_HSYNC   16
#define TFT_PCLK    21

#define TFT_R0      11
#define TFT_R1      12
#define TFT_R2      13
#define TFT_R3      14
#define TFT_R4      0

#define TFT_G0      8
#define TFT_G1      20
#define TFT_G2      3
#define TFT_G3      46
#define TFT_G4      9
#define TFT_G5      10

#define TFT_B0      4
#define TFT_B1      5
#define TFT_B2      6
#define TFT_B3      7
#define TFT_B4      15

// Touch pins (CST826 - I2C)
#define TOUCH_SDA   1
#define TOUCH_SCL   2
#define TOUCH_INT   -1
#define TOUCH_RST   -1

// Encoder pins (using GPIOs that don't conflict with display)
#define ENCODER_A   41
#define ENCODER_B   42
#define ENCODER_BTN 40

class LGFX : public lgfx::LGFX_Device
{
    lgfx::Panel_ST7701 _panel_instance;
    lgfx::Bus_RGB _bus_instance;
    lgfx::Light_PWM _light_instance;
    lgfx::Touch_CST816S _touch_instance;

public:
    LGFX(void)
    {
        // Bus configuration for RGB interface
        {
            auto cfg = _bus_instance.config();
            cfg.panel = &_panel_instance;

            cfg.pin_d0  = TFT_B0;
            cfg.pin_d1  = TFT_B1;
            cfg.pin_d2  = TFT_B2;
            cfg.pin_d3  = TFT_B3;
            cfg.pin_d4  = TFT_B4;
            cfg.pin_d5  = TFT_G0;
            cfg.pin_d6  = TFT_G1;
            cfg.pin_d7  = TFT_G2;
            cfg.pin_d8  = TFT_G3;
            cfg.pin_d9  = TFT_G4;
            cfg.pin_d10 = TFT_G5;
            cfg.pin_d11 = TFT_R0;
            cfg.pin_d12 = TFT_R1;
            cfg.pin_d13 = TFT_R2;
            cfg.pin_d14 = TFT_R3;
            cfg.pin_d15 = TFT_R4;

            cfg.pin_henable = TFT_DE;
            cfg.pin_vsync = TFT_VSYNC;
            cfg.pin_hsync = TFT_HSYNC;
            cfg.pin_pclk = TFT_PCLK;

            cfg.freq_write = 12000000;
            cfg.hsync_polarity = 0;
            cfg.hsync_front_porch = 10;
            cfg.hsync_pulse_width = 8;
            cfg.hsync_back_porch = 50;
            cfg.vsync_polarity = 0;
            cfg.vsync_front_porch = 10;
            cfg.vsync_pulse_width = 8;
            cfg.vsync_back_porch = 20;
            cfg.pclk_idle_high = 0;

            _bus_instance.config(cfg);
        }

        // Panel configuration
        {
            auto cfg = _panel_instance.config();
            cfg.memory_width  = 480;
            cfg.memory_height = 480;
            cfg.panel_width  = 480;
            cfg.panel_height = 480;
            cfg.offset_x = 0;
            cfg.offset_y = 0;
            _panel_instance.config(cfg);
        }

        _panel_instance.setBus(&_bus_instance);

        // Backlight configuration
        {
            auto cfg = _light_instance.config();
            cfg.pin_bl = TFT_BL;
            cfg.invert = false;
            cfg.freq = 12000;
            cfg.pwm_channel = 0;
            _light_instance.config(cfg);
        }
        _panel_instance.setLight(&_light_instance);

        // Touch configuration (CST816S/CST826)
        {
            auto cfg = _touch_instance.config();
            cfg.i2c_port = 0;
            cfg.i2c_addr = 0x15;
            cfg.pin_sda = TOUCH_SDA;
            cfg.pin_scl = TOUCH_SCL;
            cfg.pin_int = TOUCH_INT;
            cfg.pin_rst = TOUCH_RST;
            cfg.freq = 400000;
            cfg.x_min = 0;
            cfg.x_max = 479;
            cfg.y_min = 0;
            cfg.y_max = 479;
            _touch_instance.config(cfg);
        }
        _panel_instance.setTouch(&_touch_instance);

        setPanel(&_panel_instance);
    }
};

#endif // DISPLAY_CONFIG_H
