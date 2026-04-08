#include <string>
#include <vector>   // Ensure vector is included
#include <iostream>
#include <fstream>  // For file I/O

using namespace std;

// Function to save the checkpoint
void save_checkpoint(const string& filename, const vector<double>& A, const vector<double>& b, const vector<double>& x, 
                     int iter, double global_error) {
    ofstream file(filename, ios::binary);
    if (!file.is_open()) {
        cerr << "Error: Could not open checkpoint file for writing.\n";
        return;
    }
    size_t size_A = A.size();
    size_t size_b = b.size();
    size_t size_x = x.size();
    file.write(reinterpret_cast<const char*>(&size_A), sizeof(size_A));
    file.write(reinterpret_cast<const char*>(A.data()), size_A * sizeof(double));
    file.write(reinterpret_cast<const char*>(&size_b), sizeof(size_b));
    file.write(reinterpret_cast<const char*>(b.data()), size_b * sizeof(double));
    file.write(reinterpret_cast<const char*>(&size_x), sizeof(size_x));
    file.write(reinterpret_cast<const char*>(x.data()), size_x * sizeof(double));
    file.write(reinterpret_cast<const char*>(&iter), sizeof(iter));
    file.write(reinterpret_cast<const char*>(&global_error), sizeof(global_error));
    file.close();
}

// Function to restore the checkpoint
bool restore_checkpoint(const string& filename, vector<double>& A, vector<double>& b, vector<double>& x, 
                        int& iter, double& global_error) {
    ifstream file(filename, ios::binary);
    if (!file.is_open()) {
        cerr << "No checkpoint file found.\n";
        return false;
    }
    size_t size_A, size_b, size_x;
    file.read(reinterpret_cast<char*>(&size_A), sizeof(size_A));
    if (size_A != A.size()) {
        cerr << "Checkpoint file mismatch with matrix size for A.\n";
        return false;
    }
    file.read(reinterpret_cast<char*>(A.data()), size_A * sizeof(double));
    file.read(reinterpret_cast<char*>(&size_b), sizeof(size_b));
    if (size_b != b.size()) {
        cerr << "Checkpoint file mismatch with matrix size for b.\n";
        return false;
    }
    file.read(reinterpret_cast<char*>(b.data()), size_b * sizeof(double));
    file.read(reinterpret_cast<char*>(&size_x), sizeof(size_x));
    if (size_x != x.size()) {
        cerr << "Checkpoint file mismatch with matrix size for x.\n";
        return false;
    }
    file.read(reinterpret_cast<char*>(x.data()), size_x * sizeof(double));
    file.read(reinterpret_cast<char*>(&iter), sizeof(iter));
    file.read(reinterpret_cast<char*>(&global_error), sizeof(global_error));
    file.close();
    return true;
}
