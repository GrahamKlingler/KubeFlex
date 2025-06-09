#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>
#include <string.h>

#define ARRAY_SIZE (1024 * 1024)  // 1 million integers = 4MB per thread

void* work(void* arg) {
    int thread_id = *(int*)arg;
    int* data = malloc(sizeof(int) * ARRAY_SIZE);
    if (!data) {
        perror("malloc failed");
        pthread_exit(NULL);
    }

    // Fill array with thread_id initially
    memset(data, thread_id, ARRAY_SIZE * sizeof(int));

    long counter = 0;
    while (1) {
        // Heavy CPU + memory usage
        for (int i = 1; i < ARRAY_SIZE - 1; i++) {
            data[i] = (data[i - 1] + data[i] + data[i + 1]) % 1000000007;
        }

        // Occasionally simulate cache pollution
        if (++counter % 100 == 0) {
            for (int i = 0; i < ARRAY_SIZE; i += 4096) {
                data[i] ^= counter;
            }
        }
    }

    free(data);
    return NULL;
}

int main(int argc, char *argv[]) {
    int num_threads = (argc > 1) ? atoi(argv[1]) : 4;
    pthread_t* threads = malloc(sizeof(pthread_t) * num_threads);
    int* ids = malloc(sizeof(int) * num_threads);

    if (!threads || !ids) {
        perror("malloc failed");
        return 1;
    }

    for (int i = 0; i < num_threads; i++) {
        ids[i] = i;
        if (pthread_create(&threads[i], NULL, work, &ids[i]) != 0) {
            perror("pthread_create failed");
            return 1;
        }
    }

    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
    }

    free(threads);
    free(ids);
    return 0;
}
