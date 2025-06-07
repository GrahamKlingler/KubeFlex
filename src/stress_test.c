#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <sys/types.h>
#include <fcntl.h>
#include <string.h>
#include <pthread.h>

#define ARRAY_SIZE 1000000
#define MEMORY_SIZE (1024 * 1024 * 100) // 100MB per thread

volatile int running = 1;
pthread_t* threads;
int** memory_arrays;
int num_threads;

void handle_signal(int sig) {
    running = 0;
}

void* stress_thread(void* arg) {
    int thread_id = *(int*)arg;
    int* array = memory_arrays[thread_id];
    char filename[64];
    FILE* file = NULL;
    
    // Create a unique file for this thread
    snprintf(filename, sizeof(filename), "/tmp/stress_thread_%d.log", thread_id);
    file = fopen(filename, "a");
    if (file) {
        fprintf(file, "Thread %d started\n", thread_id);
        fflush(file);
    }
    
    while (running) {
        // CPU stress
        for (int i = 0; i < ARRAY_SIZE; i++) {
            array[i] = array[i] * array[i] + array[i];
        }
        
        // Memory stress
        for (int i = 0; i < MEMORY_SIZE / sizeof(int); i++) {
            array[i] = array[i] ^ array[i + 1];
        }
        
        // Log progress
        if (file) {
            time_t now = time(NULL);
            fprintf(file, "Thread %d: CPU and memory operations completed at %s", 
                    thread_id, ctime(&now));
            fflush(file);
        }
        
        usleep(100000); // 100ms delay
    }
    
    if (file) {
        fprintf(file, "Thread %d shutting down\n", thread_id);
        fclose(file);
    }
    
    return NULL;
}

int main(int argc, char* argv[]) {
    freopen("/dev/null", "w", stdout);
    freopen("/dev/null", "w", stderr);
    
    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    
    // Get thread count from environment variable
    char* thread_count_str = getenv("STRESS_THREAD_COUNT");
    num_threads = thread_count_str ? atoi(thread_count_str) : 4;
    
    if (num_threads < 1 || num_threads > 32) {
        fprintf(stderr, "Invalid thread count: %d\n", num_threads);
        return 1;
    }
    
    FILE *f = fopen("/tmp/stress.log", "a");
    if (!f) return 1;
    
    fprintf(f, "Starting stress test with %d threads\n", num_threads);
    
    // Allocate arrays for threads and memory
    threads = (pthread_t*)malloc(num_threads * sizeof(pthread_t));
    memory_arrays = (int**)malloc(num_threads * sizeof(int*));
    
    if (!threads || !memory_arrays) {
        fprintf(f, "Failed to allocate thread arrays\n");
        return 1;
    }
    
    // Allocate memory for each thread
    for (int i = 0; i < num_threads; i++) {
        memory_arrays[i] = (int*)malloc(MEMORY_SIZE);
        if (!memory_arrays[i]) {
            fprintf(f, "Failed to allocate memory for thread %d\n", i);
            return 1;
        }
        memset(memory_arrays[i], i, MEMORY_SIZE);
    }
    
    // Create threads
    int* thread_ids = (int*)malloc(num_threads * sizeof(int));
    for (int i = 0; i < num_threads; i++) {
        thread_ids[i] = i;
        if (pthread_create(&threads[i], NULL, stress_thread, &thread_ids[i]) != 0) {
            fprintf(f, "Failed to create thread %d\n", i);
            return 1;
        }
        fprintf(f, "Created thread %d\n", i);
    }
    
    // Main loop
    int counter = 0;
    while (running) {
        time_t now = time(NULL);
        fprintf(f, "Stress test count: %d, Time: %s", counter++, ctime(&now));
        fflush(f);
        sleep(2);
    }
    
    // Cleanup
    fprintf(f, "Stress test shutting down\n");
    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
        free(memory_arrays[i]);
    }
    free(threads);
    free(memory_arrays);
    free(thread_ids);
    fclose(f);
    return 0;
} 