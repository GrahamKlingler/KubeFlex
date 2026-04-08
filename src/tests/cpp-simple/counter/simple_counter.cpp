// Simple C++ counter that logs to stdout and /script-data/container.log
#include <sys/types.h>
#include <unistd.h>
#include <stdio.h>
#include <time.h>
#include <stdio.h>
#include <time.h>

extern "C" {
int main() {
  unsigned long counter = 0;
  while (true) {
    pid_t pid = getpid();
    time_t rawtime;
    struct tm *timeinfo;
    time(&rawtime);
    timeinfo = localtime(&rawtime);
    FILE *f = fopen("/script-data/container.log", "a");
    if (f) {
      fprintf(f, "PID: %d, Count: %lu, Time: %s", pid, counter,
              asctime(timeinfo));
      fclose(f);
    }
    ++counter;
    sleep(20);
  }
  return 0;
}
}
//   unsigned long counter = 0;
//   pid_t pid = getpid();
//   while (true) {
//     auto now = std::chrono::system_clock::now();
//     std::time_t t = std::chrono::system_clock::to_time_t(now);
//     std::stringstream ss;
//     ss << "Counter: " << counter << ", Time: " << std::ctime(&t);
//     std::string out = ss.str();
//     // ctime adds a newline already
//     std::cout << "PID: " << pid << " - " << out << std::flush;
//     // also append to /script-data/container.log if available
//     try {
//       std::ofstream f("/script-data/container.log", std::ios::app);
//       if (f) {
//         f << "PID: " << pid << " - " << out;
//       }
//     } catch (...) {
//       // ignore
//     }
//     ++counter;
//     std::this_thread::sleep_for(std::chrono::seconds(5));
//   }
//   return 0;
// }
