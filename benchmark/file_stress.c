#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <time.h>

#define WRITE_SIZE 4096  // 4 KB per write
#define WRITES_PER_THREAD 100   // how many writes per thread per loop
#define FLUSH_EVERY 10

int main(int argc, char *argv[]) {
    int threads = (argc > 1) ? atoi(argv[1]) : 4;

    // Create large buffer to write
    char data[WRITE_SIZE];
    memset(data, 'A', WRITE_SIZE);
    data[WRITE_SIZE - 1] = '\n';

    mkdir("/tmp/file_stress", 0755);

    while (1) {
        for (int i = 0; i < threads; i++) {
            char fname[128];
            snprintf(fname, sizeof(fname), "/tmp/file_stress/thread_%d_%ld.txt", i, time(NULL));
            int fd = open(fname, O_WRONLY | O_CREAT | O_TRUNC, 0644);
            if (fd < 0) continue;

            for (int w = 0; w < WRITES_PER_THREAD; w++) {
                if (write(fd, data, WRITE_SIZE) < 0) break;
                if (w % FLUSH_EVERY == 0) fsync(fd);  // force flush every few writes
            }

            close(fd);
        }
        usleep(50000); // 50ms pause
    }

    return 0;
}