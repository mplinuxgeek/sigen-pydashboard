add_library(usermod_rgb_lcd INTERFACE)
target_sources(usermod_rgb_lcd INTERFACE ${CMAKE_CURRENT_LIST_DIR}/rgb_lcd.c)
target_include_directories(usermod_rgb_lcd INTERFACE ${CMAKE_CURRENT_LIST_DIR})
target_link_libraries(usermod INTERFACE usermod_rgb_lcd)
# NOTE: esp_lcd, esp_driver_gpio must be listed in IDF_COMPONENTS of micropython/ports/esp32/esp32_common.cmake (patched locally).
