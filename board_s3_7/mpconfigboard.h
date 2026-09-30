#define MICROPY_HW_BOARD_NAME               "Waveshare ESP32-S3-Touch-LCD-7"
#define MICROPY_HW_MCU_NAME                 "ESP32-S3"

// Native USB (CDC) console is the default; the board also has a CH343 UART bridge on UART0.
#define MICROPY_HW_ENABLE_UART_REPL         (1)

// GT911 touch + CH422G IO expander share this bus.
#define MICROPY_HW_I2C0_SCL                 (9)
#define MICROPY_HW_I2C0_SDA                 (8)

#define MICROPY_HW_HAS_LVGL (1)

// zlib compression (PNG screenshots, etc.)
#define MICROPY_PY_DEFLATE_COMPRESS (1)

// mDNS: answer as <hostname>.local and resolve .local names
#define MICROPY_HW_ENABLE_MDNS_RESPONDER (1)
#define MICROPY_HW_ENABLE_MDNS_QUERIES (1)
