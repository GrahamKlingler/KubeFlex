
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>

void* mixed_work(void* arg) {
    int id = *((int*)arg);
    char fname[64];
    snprintf(fname, sizeof(fname), "/tmp/mixed_file_%d.txt", id);
    char data[] = "Mixed workload data\n";
    while (1) {
        // Simulate CPU
        for (volatile int i = 0; i < 1000000; i++);
        // Simulate file I/O
        int fd = open(fname, O_WRONLY | O_CREAT | O_APPEND, 0644);
        if (fd >= 0) {
            write(fd, data, strlen(data));
            close(fd);
        }
        usleep(50000); // slight delay
    }
    return NULL;
}

int main(int argc, char *argv[]) {
    int num_threads = (argc > 1) ? atoi(argv[1]) : 4;
    pthread_t threads[num_threads];
    int ids[num_threads];
    for (int i = 0; i < num_threads; i++) {
        ids[i] = i;
        pthread_create(&threads[i], NULL, mixed_work, &ids[i]);
    }
    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
    }
    return 0;
}

