# Source this only on the validation VM, or supply your own tool environment.
export VERDI_HOME=${VERDI_HOME:-/home/synopsys/verdi/Verdi_O-2018.09-SP2}
export VCS_HOME=${VCS_HOME:-/home/synopsys/vcs-mx/O-2018.09-SP2}
export SNPSLMD_LICENSE_FILE=${SNPSLMD_LICENSE_FILE:-27000@IC_EDA}
export PATH="$VCS_HOME/bin:$VERDI_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$VERDI_HOME/share/PLI/VCS/LINUX64:$VERDI_HOME/share/NPI/lib/LINUX64:${LD_LIBRARY_PATH:-}"
