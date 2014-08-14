#!/bin/bash
#
# acts like the Safenet lunadiag utility by dumping out canned outputs
#
#  lunadiag -s=1 -c=< CMD_NUM-after-stripping >

cd ./hsm_canned_output
#ls -1 

CMD_NUM=${2##-c=}

cat ${CMD_NUM}.out

#sleep 5
