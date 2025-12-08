#!/bin/bash

# Flex-Nautilus Requirements Installation Script
# This script installs all required dependencies for Flex-Nautilus

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
}

# Detect OS
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        OS="windows"
    else
        OS="unknown"
    fi
    log_info "Detected OS: $OS"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check version of a command
check_version() {
    local cmd=$1
    local min_version=$2
    local version_cmd=$3
    
    if ! command_exists "$cmd"; then
        return 1
    fi
    
    local version=$($version_cmd 2>/dev/null | head -n 1)
    log_info "Found $cmd: $version"
    return 0
}

# Install Docker Desktop (macOS)
install_docker_macos() {
    log_step "Installing Docker Desktop for macOS..."
    
    if command_exists docker; then
        log_success "Docker is already installed"
        local docker_version=$(docker --version | grep -oE 'version [0-9]+\.[0-9]+\.[0-9]+' | awk '{print $2}')
        log_info "Found Docker version: $docker_version"
        
        # Check for Docker Desktop 4.48.0 or compatible
        if docker version 2>/dev/null | grep -q "Docker Desktop 4\.[4-9][0-9]\|Docker Desktop 4\.[0-9][0-9][0-9]"; then
            log_success "Docker Desktop version is compatible (4.48.0 or later)"
        elif docker version 2>/dev/null | grep -q "Docker Desktop"; then
            log_warning "Docker Desktop version may be outdated. Recommended: 4.48.0 or later."
        fi
        return 0
    fi
    
    log_info "Docker Desktop is not installed."
    log_info "Please install Docker Desktop manually:"
    log_info "  1. Visit: https://www.docker.com/products/docker-desktop"
    log_info "  2. Download Docker Desktop for Mac"
    log_info "  3. Install and start Docker Desktop (recommended: 4.48.0 or later)"
    log_info "  4. Run this script again"
    
    return 1
}

# Install Docker (Linux)
install_docker_linux() {
    log_step "Installing Docker Engine for Linux..."
    
    if command_exists docker; then
        log_success "Docker is already installed"
        local docker_version=$(docker --version | grep -oE 'version [0-9]+\.[0-9]+\.[0-9]+' | awk '{print $2}')
        log_info "Found Docker version: $docker_version"
        return 0
    fi
    
    log_info "Installing Docker Engine..."
    
    # Detect Linux distribution
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
        VERSION_CODENAME=$VERSION_CODENAME
        if [ -z "$VERSION_CODENAME" ]; then
            VERSION_CODENAME=$(lsb_release -cs)
        fi
    else
        DISTRO="ubuntu"
        VERSION_CODENAME=$(lsb_release -cs)
    fi
    
    log_info "Detected distribution: $DISTRO ($VERSION_CODENAME)"
    
    # Update package index
    sudo apt-get update
    
    # Install prerequisites
    sudo apt-get install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release
    
    # Add Docker's official GPG key
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/${DISTRO}/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    
    # Set up repository based on distribution
    if [ "$DISTRO" = "debian" ]; then
        log_info "Setting up Docker repository for Debian..."
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
          $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    else
        log_info "Setting up Docker repository for Ubuntu..."
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    fi
    
    # Install Docker Engine
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    # Add current user to docker group
    sudo usermod -aG docker $USER
    
    log_success "Docker Engine installed successfully"
    log_warning "You may need to log out and log back in for group changes to take effect"
    log_warning "Or run: newgrp docker"
}

# Install kubectl
install_kubectl() {
    log_step "Installing kubectl..."
    
    if command_exists kubectl; then
        log_success "kubectl is already installed"
        local kubectl_version=$(kubectl version --client --short 2>/dev/null | awk '{print $3}' | sed 's/v//' || kubectl version --client 2>/dev/null | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 | sed 's/v//')
        log_info "Found kubectl version: $kubectl_version"
        
        # Check if version is >= 1.32.0 (to match server version compatibility)
        local major=$(echo $kubectl_version | cut -d. -f1)
        local minor=$(echo $kubectl_version | cut -d. -f2)
        
        if [[ $major -gt 1 ]] || [[ $major -eq 1 && $minor -ge 32 ]]; then
            log_success "kubectl version is compatible (>= 1.32.0, recommended: 1.33.1)"
        else
            log_warning "kubectl version may be outdated. Recommended: 1.33.1 or later."
        fi
        return 0
    fi
    
    if [[ "$OS" == "macos" ]]; then
        log_info "Installing kubectl v1.33.1 via Homebrew..."
        if command_exists brew; then
            # Install specific version or latest
            brew install kubectl
            log_success "kubectl installed successfully"
            log_info "To ensure version 1.33.1, you may need to:"
            log_info "  brew install kubectl@1.33"
        else
            log_error "Homebrew is not installed. Please install Homebrew first:"
            log_info "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            return 1
        fi
    elif [[ "$OS" == "linux" ]]; then
        log_info "Installing kubectl v1.33.1..."
        
        # Download specific version
        curl -LO "https://dl.k8s.io/release/v1.33.1/bin/linux/amd64/kubectl"
        
        # Verify checksum (optional but recommended)
        curl -LO "https://dl.k8s.io/v1.33.1/bin/linux/amd64/kubectl.sha256"
        echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check || log_warning "Checksum verification failed, continuing anyway..."
        
        # Install kubectl
        sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
        
        # Cleanup
        rm kubectl kubectl.sha256
        
        log_success "kubectl v1.33.1 installed successfully"
    else
        log_error "kubectl installation not supported for $OS"
        log_info "Please install kubectl manually: https://kubernetes.io/docs/tasks/tools/"
        return 1
    fi
}

# Install KIND
install_kind() {
    log_step "Installing KIND (Kubernetes in Docker)..."
    
    if command_exists kind; then
        log_success "KIND is already installed"
        local kind_version=$(kind --version 2>/dev/null | awk '{print $3}' | sed 's/v//')
        log_info "Found KIND version: $kind_version"
        
        # Check if version is >= 0.27.0 (recommended version)
        local major=$(echo $kind_version | cut -d. -f1)
        local minor=$(echo $kind_version | cut -d. -f2)
        
        if [[ $major -gt 0 ]] || [[ $major -eq 0 && $minor -ge 27 ]]; then
            log_success "KIND version is compatible (>= 0.27.0, recommended: 0.27.0)"
        else
            log_warning "KIND version may be outdated. Recommended: 0.27.0 or later."
        fi
        return 0
    fi
    
    if [[ "$OS" == "macos" ]]; then
        log_info "Installing KIND v0.27.0 via Homebrew..."
        if command_exists brew; then
            brew install kind
            log_success "KIND installed successfully"
            log_info "Note: Homebrew may install latest version. For v0.27.0 specifically:"
            log_info "  brew install kind@0.27"
        else
            log_error "Homebrew is not installed. Please install Homebrew first."
            return 1
        fi
    elif [[ "$OS" == "linux" ]]; then
        log_info "Installing KIND v0.27.0..."
        
        # Detect architecture
        ARCH=$(uname -m)
        if [[ "$ARCH" == "x86_64" ]]; then
            KIND_ARCH="amd64"
        elif [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
            KIND_ARCH="arm64"
        else
            KIND_ARCH="amd64"  # Default
            log_warning "Unknown architecture, defaulting to amd64"
        fi
        
        # Download specific version
        curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.27.0/kind-linux-${KIND_ARCH}"
        chmod +x ./kind
        sudo mv ./kind /usr/local/bin/kind
        
        log_success "KIND v0.27.0 installed successfully"
    else
        log_error "KIND installation not supported for $OS"
        log_info "Please install KIND manually: https://kind.sigs.k8s.io/docs/user/quick-start/#installation"
        return 1
    fi
}

# Install Python
install_python() {
    log_step "Checking Python installation..."
    
    if command_exists python3; then
        local python_version=$(python3 --version 2>&1 | awk '{print $2}')
        log_success "Python is already installed: $python_version"
        
        # Check if version is >= 3.9
        local major=$(echo $python_version | cut -d. -f1)
        local minor=$(echo $python_version | cut -d. -f2)
        
        if [[ $major -gt 3 ]] || [[ $major -eq 3 && $minor -ge 9 ]]; then
            log_success "Python version is compatible (>= 3.9)"
            return 0
        else
            log_warning "Python version is too old. Please upgrade to 3.9 or later."
            return 1
        fi
    fi
    
    if [[ "$OS" == "macos" ]]; then
        log_info "Installing Python via Homebrew..."
        if command_exists brew; then
            brew install python3
            log_success "Python installed successfully"
        else
            log_error "Homebrew is not installed. Please install Homebrew first."
            return 1
        fi
    elif [[ "$OS" == "linux" ]]; then
        log_info "Installing Python..."
        sudo apt-get update
        sudo apt-get install -y python3 python3-pip python3-venv
        log_success "Python installed successfully"
    else
        log_error "Python installation not supported for $OS"
        log_info "Please install Python 3.9+ manually: https://www.python.org/downloads/"
        return 1
    fi
}

# Verify installations
verify_installations() {
    log_step "Verifying installations..."
    
    local all_ok=true
    
    # Check Docker
    if command_exists docker; then
        log_success "✓ Docker is installed"
        docker --version
        if docker version 2>/dev/null | grep -q "Docker Desktop"; then
            docker version 2>/dev/null | grep "Docker Desktop" | head -n 1 || true
            log_info "  Recommended: Docker Desktop 4.48.0 (matches your setup)"
        fi
    else
        log_error "✗ Docker is not installed"
        all_ok=false
    fi
    
    # Check kubectl
    if command_exists kubectl; then
        log_success "✓ kubectl is installed"
        kubectl version --client --short 2>/dev/null || kubectl version --client
        log_info "  Recommended: v1.33.1 (matches your setup)"
    else
        log_error "✗ kubectl is not installed"
        all_ok=false
    fi
    
    # Check KIND
    if command_exists kind; then
        log_success "✓ KIND is installed"
        kind --version
        log_info "  Recommended: v0.27.0 (matches your setup)"
    else
        log_error "✗ KIND is not installed"
        all_ok=false
    fi
    
    # Check Python
    if command_exists python3; then
        log_success "✓ Python is installed"
        python3 --version
    else
        log_error "✗ Python is not installed"
        all_ok=false
    fi
    
    if [[ "$all_ok" == true ]]; then
        log_success "All required tools are installed!"
        return 0
    else
        log_error "Some tools are missing. Please install them and run this script again."
        return 1
    fi
}

# Main installation function
main() {
    echo "=========================================="
    echo "  Flex-Nautilus Requirements Installer"
    echo "=========================================="
    echo ""
    
    detect_os
    
    if [[ "$OS" == "unknown" ]]; then
        log_error "Unsupported operating system: $OSTYPE"
        exit 1
    fi
    
    if [[ "$OS" == "windows" ]]; then
        log_error "Windows is not directly supported. Please use WSL2."
        log_info "For Windows, please:"
        log_info "  1. Install WSL2: https://docs.microsoft.com/en-us/windows/wsl/install"
        log_info "  2. Run this script from within WSL2"
        exit 1
    fi
    
    log_info "This script will install the following:"
    log_info "  - Docker Desktop (macOS 4.48.0+) or Docker Engine (Linux)"
    log_info "  - kubectl (v1.33.1 recommended, >= v1.32.0)"
    log_info "  - KIND (v0.27.0 recommended, >= v0.20.0)"
    log_info "  - Python (3.9+)"
    echo ""
    
    read -p "Do you want to continue? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Installation cancelled."
        exit 0
    fi
    
    # Install Docker
    if [[ "$OS" == "macos" ]]; then
        install_docker_macos || log_warning "Docker Desktop installation requires manual steps"
    elif [[ "$OS" == "linux" ]]; then
        install_docker_linux
    fi
    
    # Install kubectl
    install_kubectl
    
    # Install KIND
    install_kind
    
    # Install Python
    install_python
    
    # Verify installations
    echo ""
    verify_installations
    
    echo ""
    log_success "Installation complete!"
    echo ""
    log_info "Next steps:"
    log_info "  1. Ensure Docker is running (Docker Desktop on macOS)"
    log_info "  2. If you installed Docker on Linux, you may need to log out and back in"
    log_info "  3. Navigate to the src/ directory and run: ./run.sh --all --include-cluster --include-db"
    echo ""
}

# Run main function
main "$@"

