// Simple C++ counter that logs to stdout and /script-data/container.log
#include <chrono>
#include <ctime>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <sys/types.h>
#include <thread>
#include <unistd.h>

int main() {
  unsigned long counter = 0;
  pid_t pid = getpid();
  while (true) {
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::stringstream ss;
    ss << "Counter: " << counter << ", Time: " << std::ctime(&t);
    std::string out = ss.str();
    // ctime adds a newline already
    std::cout << "PID: " << pid << " - " << out << std::flush;
    // also append to /script-data/container.log if available
    try {
      std::ofstream f("/script-data/container.log", std::ios::app);
      if (f) {
        f << "PID: " << pid << " - " << out;
      }
    } catch (...) {
      // ignore
    }
    ++counter;
    std::this_thread::sleep_for(std::chrono::seconds(5));
  }
  return 0;
}
