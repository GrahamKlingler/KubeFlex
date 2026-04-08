#ifndef MAIN_H
#define MAIN_H

#include <string>
#include <CLI11.hpp>
#include <vector>  
using namespace std;

void jacobi_richardson(std::vector<double>& A, std::vector<double>& b, std::vector<double>& x, int local_rows, int rank, int size, int& iter, double& global_error);
void save_checkpoint(const string& filename, const vector<double>& A, const vector<double>& b, const vector<double>& x, int iter, double global_error);
bool restore_checkpoint(const string& filename, vector<double>& A, vector<double>& b, vector<double>& x, int& iter, double& global_error);

#endif