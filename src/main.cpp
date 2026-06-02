#include <Arduino.h>
#include <WiFi.h>

const char* WIFI_SSID = "Weng";
const char* WIFI_PASSWORD = "88888888";

const char* SERVER_IP = "172.20.10.4";
const uint16_t SERVER_PORT = 5555;

WiFiClient client;

int bpm = 72;

void connectWiFi() {
    Serial.print("Connecting to WiFi");

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.print("WiFi connected. ESP32 IP: ");
    Serial.println(WiFi.localIP());
}

void connectServer() {
    while (!client.connected()) {
        Serial.print("Connecting to TCP server... ");

        if (client.connect(SERVER_IP, SERVER_PORT)) {
            Serial.println("connected");
        } else {
            Serial.println("failed, retrying...");
            delay(1000);
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    connectWiFi();
    connectServer();
}

void loop() {
    if (!client.connected()) {
        connectServer();
    }

    bpm += random(-1, 2);

    float ax = random(-30, 31) / 100.0;
    float ay = random(-30, 31) / 100.0;
    float az = 1.0 + random(-10, 11) / 100.0;

    char packet[256];

    snprintf(
        packet,
        sizeof(packet),
        "{\"type\":\"sample\",\"ts\":%lu,\"hr\":{\"bpm\":%d},\"accel\":{\"x\":%.2f,\"y\":%.2f,\"z\":%.2f}}",
        millis(),
        bpm,
        ax,
        ay,
        az
    );

    client.println(packet);
    Serial.println(packet);

    delay(1000);
}
