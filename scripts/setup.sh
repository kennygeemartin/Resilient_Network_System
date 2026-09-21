#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 22.04 && "$(uname -m)" == x86_64 ]] || { echo 'Ubuntu 22.04 x86-64 required'; exit 1; }
sudo apt-get update
sudo apt-get install -y build-essential git curl ca-certificates python3 python3-dev python3-venv python3-pip openjdk-11-jdk iperf3 iproute2 net-tools ethtool iputils-ping psmisc openvswitch-switch autoconf automake libtool pkg-config libssl-dev libcap-ng-dev tcpdump
git submodule update --init --recursive
[[ "$(git -C third_party/ifogsim rev-parse --short=7 HEAD)" == 643c433 ]]
[[ "$(git -C third_party/mininet rev-parse --short=7 HEAD)" == 88f14e9 ]]
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade 'pip==24.3.1' 'setuptools==75.6.0' 'wheel==0.45.1'
.venv/bin/python -m pip install -r requirements.txt
sudo python3 -m pip install --no-deps ./third_party/mininet
.venv/bin/python -m pip install --no-deps ./third_party/mininet
make -C third_party/mininet PYTHON=python3 mnexec
sudo install -m 0755 third_party/mininet/mnexec /usr/bin/mnexec
mkdir -p third_party/ovs-build results/environment
curl --fail --location https://www.openvswitch.org/releases/openvswitch-3.7.1.tar.gz -o third_party/ovs-build/ovs.tar.gz
sha256sum third_party/ovs-build/ovs.tar.gz > results/environment/ovs_archive.sha256
tar -xzf third_party/ovs-build/ovs.tar.gz -C third_party/ovs-build
(
  cd third_party/ovs-build/openvswitch-3.7.1
  ./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var
  make -j"$(nproc)"
  sudo systemctl stop openvswitch-switch
  sudo make install
  sudo systemctl start openvswitch-switch
)
.venv/bin/python -m pip freeze --all > results/environment/requirements.resolved.txt
JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 PATH=/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH .venv/bin/python -m scripts.capture_environment
echo 'Setup complete. Inspect environment manifest before make smoke.'
