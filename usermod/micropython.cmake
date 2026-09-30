# Top-level USER_C_MODULES entry: display driver + LVGL bindings.
set(LV_CONF_PATH ${CMAKE_CURRENT_LIST_DIR}/../board_s3_7/lv_conf.h CACHE STRING "" FORCE)
include(${CMAKE_CURRENT_LIST_DIR}/rgb_lcd/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/../lv_binding_micropython/micropython.cmake)
