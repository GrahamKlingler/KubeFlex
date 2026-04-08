// Standalone (no-MPI) version of the N-body simulation for CRIU migration testing.
// Identical computation to main.cpp but with all MPI calls removed.
// Single-process only — no inter-rank communication needed.

#include <cstdio>
#include <cstring>
#include <iostream>
#include <fstream>
#include <cmath>
#include <vector>
#include <string>
#include <sys/stat.h>
#include <sys/time.h>
#include <CLI11.hpp>

using namespace std;

typedef struct {
	double x, y, z;
	double vx, vy, vz;
	double mass;
} Body;

double wtime() {
	struct timeval tv;
	gettimeofday(&tv, NULL);
	return tv.tv_sec + tv.tv_usec * 1e-6;
}

long get_rank_bodies(long total_bodies, int rank, int size) {
	long base = total_bodies / size;
	long watershed = total_bodies % size;
	return (rank < watershed) ? base + 1 : base;
}

void create_bodies_static(Body *bodies, long total_bodies, int rank, int size, long start) {
	long rank_bodies = get_rank_bodies(total_bodies, rank, size);
	for (long i = 0; i < rank_bodies; i++) {
		long n = start + i;
		bodies[i].x = n;
		bodies[i].y = n;
		bodies[i].z = n;
		bodies[i].vx = n * n;
		bodies[i].vy = n * n;
		bodies[i].vz = n * n;
		bodies[i].mass = 1.0 / total_bodies;
	}
}

void compute_velocity(Body *local, Body *incoming, double dt, long nlocal, long nremote) {
	double G = 1.0;
	double softening = 0.1;
	for (long i = 0; i < nlocal; i++) {
		double Fx = 0.0, Fy = 0.0, Fz = 0.0;
		for (long j = 0; j < nremote; j++) {
			double dx = incoming[j].x - local[i].x;
			double dy = incoming[j].y - local[i].y;
			double dz = incoming[j].z - local[i].z;
			double distance = sqrt(dx*dx + dy*dy + dz*dz + softening*softening);
			double distance_cubed = distance * distance * distance;
			double mGd = G * local[j].mass / distance_cubed;
			Fx += mGd * dx;
			Fy += mGd * dy;
			Fz += mGd * dz;
		}
		local[i].vx += dt * Fx;
		local[i].vy += dt * Fy;
		local[i].vz += dt * Fz;
	}
}

void do_iteration(Body *local, Body *incoming, long total_bodies, long local_bodies, double dt) {
	// Single process: incoming == local
	memcpy(incoming, local, local_bodies * sizeof(Body));
	compute_velocity(local, incoming, dt, local_bodies, local_bodies);
	for (long i = 0; i < local_bodies; i++) {
		local[i].x += local[i].vx * dt;
		local[i].y += local[i].vy * dt;
		local[i].z += local[i].vz * dt;
	}
}

int checkpoint_state(Body *local, long total_bodies, int iteration, string results_folder) {
	string checkpoint_file = results_folder + "checkpoint.dat";
	ofstream wf(checkpoint_file, ios::out | ios::binary);
	if (!wf) {
		cout << "Cannot open file!" << endl;
		return 1;
	}
	wf.write((char *)&iteration, sizeof(int));
	for (long i = 0; i < total_bodies; i++)
		wf.write((char *)&local[i], sizeof(Body));
	wf.close();
	return wf.good() ? 0 : 1;
}

void write_file(string results_folder, string name, int rank, vector<double> data) {
	mkdir((results_folder + "logs/").data(), 0700);
	ofstream myFile(results_folder + "logs/" + name + "_" + to_string(rank) + ".csv");
	myFile << name << "\n";
	for (size_t i = 0; i < data.size(); ++i)
		myFile << data.at(i) << "\n";
	myFile.close();
}

void save_progress(string results_folder, double time, double progress) {
	ofstream myFile(results_folder + "progress.csv", ios_base::app);
	myFile << time << "," << progress << "\n";
	myFile.close();
}

int main(int argc, char *argv[]) {
	long total_bodies = 10;
	int checkpoint_interval = 1;
	int total_iterations = 10;
	string results_folder = "./results/";

	CLI::App app{"Elastic Nbody Simulation (no MPI)"};
	app.add_option("-b,--total-bodies", total_bodies, "Total Bodies");
	app.add_option("-c,--checkpoint-interval", checkpoint_interval, "Checkpoint interval");
	app.add_option("-f,--results-folder", results_folder, "Results Folder");
	app.add_option("-i,--iterations", total_iterations, "Total number of iterations");
	CLI11_PARSE(app, argc, argv);

	vector<double> checkpoint_time = {};
	vector<double> iteration_time = {};

	mkdir(results_folder.data(), 0700);
	results_folder = results_folder + to_string(total_bodies) + "/";
	mkdir(results_folder.data(), 0700);

	Body *local = (Body *)calloc(total_bodies, sizeof(Body));
	Body *incoming = (Body *)calloc(total_bodies, sizeof(Body));

	create_bodies_static(local, total_bodies, 0, 1, 0);

	double dt = 1;
	double start_time = wtime();

	for (int i = 0; i < total_iterations; i++) {
		double start = wtime();
		do_iteration(local, incoming, total_bodies, total_bodies, dt);
		double stop = wtime();
		iteration_time.push_back(stop - start);
		save_progress(results_folder, wtime(), (i + 1) * 100.0 / total_iterations);

		if (i % checkpoint_interval == 0) {
			double cs = wtime();
			if (checkpoint_state(local, total_bodies, i, results_folder)) {
				cout << "Aborting Program" << endl;
				return 1;
			}
			double ce = wtime();
			checkpoint_time.push_back(ce - cs);
		}
	}

	double end_time = wtime();
	cout << (end_time - start_time) / total_iterations << endl;

	write_file(results_folder, "iteration_time", 0, iteration_time);
	write_file(results_folder, "checkpoint_time", 0, checkpoint_time);

	free(local);
	free(incoming);
	return 0;
}
