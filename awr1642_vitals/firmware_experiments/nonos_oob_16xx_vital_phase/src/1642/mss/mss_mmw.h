/*
* Copyright (C) 2024 Texas Instruments Incorporated
*
* All rights reserved not granted herein.
* Limited License.  
*
* Texas Instruments Incorporated grants a world-wide, royalty-free, 
* non-exclusive license under copyrights and patents it now or hereafter 
* owns or controls to make, have made, use, import, offer to sell and sell ("Utilize")
* this software subject to the terms herein.  With respect to the foregoing patent 
* license, such license is granted  solely to the extent that any such patent is necessary 
* to Utilize the software alone.  The patent license shall not apply to any combinations which 
* include this software, other than combinations with devices manufactured by or for TI ("TI Devices").  
* No hardware patent is licensed hereunder.
*
* Redistributions must preserve existing copyright notices and reproduce this license (including the 
* above copyright notice and the disclaimer and (if applicable) source code license limitations below) 
* in the documentation and/or other materials provided with the distribution
*
* Redistribution and use in binary form, without modification, are permitted provided that the following
* conditions are met:
*
*	* No reverse engineering, decompilation, or disassembly of this software is permitted with respect to any 
*     software provided in binary form.
*	* any redistribution and use are licensed by TI for use only with TI Devices.
*	* Nothing shall obligate TI to provide you with source code for the software licensed and provided to you in object code.
*
* If software source code is provided to you, modification and redistribution of the source code are permitted 
* provided that the following conditions are met:
*
*   * any redistribution and use of the source code, including any resulting derivative works, are licensed by 
*     TI for use only with TI Devices.
*   * any redistribution and use of any object code compiled from the source code and any resulting derivative 
*     works, are licensed by TI for use only with TI Devices.
*
* Neither the name of Texas Instruments Incorporated nor the names of its suppliers may be used to endorse or 
* promote products derived from this software without specific prior written permission.
*
* DISCLAIMER.
*
* THIS SOFTWARE IS PROVIDED BY TI AND TI'S LICENSORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, 
* BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. 
* IN NO EVENT SHALL TI AND TI'S LICENSORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR 
* CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, 
* OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, 
* OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE 
* POSSIBILITY OF SUCH DAMAGE.
*/

#ifndef MSS_MMW_DEMO_H
#define MSS_MMW_DEMO_H

#include <ti/common/mmwave_error.h>
#include <ti/drivers/soc/soc.h>
#include <ti/drivers/crc/crc.h>
#include <ti/drivers/uart/UART.h>
#include <ti/drivers/pinmux/pinmux.h>
#include <ti/drivers/esm/esm.h>
#include <ti/drivers/soc/soc.h>
#include <ti/drivers/mailbox/mailbox.h>
#include <ti/control/mmwave/mmwave.h>
#include <ti/drivers/watchdog/Watchdog.h>

#include "osal_nonos/Event_nonos.h"

/* MMW Demo Include Files */
#include <ti/demo/io_interface/mmw_config.h>

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * @brief
     *  Millimeter Wave Demo statistics
     *
     * @details
     *  The structure is used to hold the statistics information for the
     *  Millimeter Wave demo
     */
    typedef struct MmwDemo_MSS_STATS_t
    {
        /*! @brief   CLI event for sensorStart */
        uint8_t cliSensorStartEvt;

        /*! @brief   CLI event for sensorStop */
        uint8_t cliSensorStopEvt;

        /*! @brief   CLI event for frameStart */
        uint8_t cliFrameStartEvt;

        /*! @brief   Counter which tracks the number of datapath config event detected
         *           The event is triggered in mmwave config callback function */
        uint8_t datapathConfigEvt;

        /*! @brief   Counter which tracks the number of datapath start event  detected
         *           The event is triggered in mmwave start callback function */
        uint8_t datapathStartEvt;

        /*! @brief   Counter which tracks the number of datapath stop event detected
         *           The event is triggered in mmwave stop callback function */
        uint8_t datapathStopEvt;

        /*! @brief   Counter which tracks the number of failed calibration reports
         *           The event is triggered by an asynchronous event from the BSS */
        uint32_t numFailedTimingReports;

        /*! @brief   Counter which tracks the number of calibration reports received
         *           The event is triggered by an asynchronous event from the BSS */
        uint32_t numCalibrationReports;
    } MmwDemo_MSS_STATS;

    /**
     * @brief
     *  Millimeter Wave Demo MCB
     *
     * @details
     *  The structure is used to hold all the relevant information for the
     *  Millimeter Wave demo
     */
    typedef struct MmwDemo_MCB_t
    {
        /*! @brief   Configuration which is used to execute the demo */
        MmwDemo_Cfg cfg;

        /*! @brief   CLI related configuration */
        MmwDemo_CliCfg_t cliCfg[RL_MAX_SUBFRAMES];

        /*! @brief   CLI related configuration common across all subframes */
        MmwDemo_CliCommonCfg_t cliCommonCfg;

        /*! * @brief   Handle to the SOC Module */
        SOC_Handle socHandle;

        /*! * @brief   Handle to the ESM Module */
        ESM_Handle esmHandle;

        /*! * @brief   Handle to the WatchDog Module */
        Watchdog_Handle watchDgHandle;

        /*! @brief   UART Logging Handle */
        UART_Handle loggingUartHandle;

        /*! @brief   UART Command Rx/Tx Handle */
        UART_Handle commandUartHandle;

        /*! @brief   This is the mmWave control handle which is used
         * to configure the BSS. */
        MMWave_Handle ctrlHandle;

        /*!@brief   Handle to the peer Mailbox */
        Mbox_Handle peerMailbox;

        /*! @brief   Semaphore handle for the mailbox communication */
        SemaphoreP_Handle mboxSemHandle;

        /*! @brief   MSS system event handle */
        Event_Handle eventHandle;

        /*! @brief   MSS system event handle */
        Event_Handle eventHandleNotify;

        /*! @brief   Handle to the SOC chirp interrupt listener Handle */
        SOC_SysIntListenerHandle chirpIntHandle;

        /*! @brief   Handle to the SOC frame start interrupt listener Handle */
        SOC_SysIntListenerHandle frameStartIntHandle;

        /*! @brief   Current status of the sensor */
        bool isSensorStarted;

        /*! @brief   Has the mmWave module been opened? */
        bool isMMWaveOpen;

        /*! @brief   mmw Demo stats */
        MmwDemo_MSS_STATS stats;

        /*! @brief DSS to MSS Isr Info Address */
        uint32_t dss2mssIsrInfoAddress;

        bool isReadyForCli;
    } MmwDemo_MCB;

    /**************************************************************************
     *************************** Extern Definitions ***************************
     **************************************************************************/
    extern int32_t MmwDemo_mssDataPathConfig(void);
    extern int32_t MmwDemo_mssDataPathStart(void);
    extern int32_t MmwDemo_mssDataPathStop(void);

    /* Sensor Management Module Exported API */
    extern int32_t MmwDemo_notifySensorStart(bool doReconfig);
    extern int32_t MmwDemo_notifySensorStop(void);
    extern int32_t MmwDemo_waitSensorStartComplete(void);
    extern int32_t MmwDemo_waitSensorStopComplete(void);

    extern void _MmwDemo_mssAssert(int32_t expression, const char *file, int32_t line);
    extern void MmwDemo_nonOsLoop(uint8_t count);
#define MmwDemo_mssAssert(expression) \
    { \
        _MmwDemo_mssAssert(expression, \
                           __FILE__, \
                           __LINE__); \
        DebugP_assert(expression); \
    }


#ifdef __cplusplus
}
#endif

#endif /* MSS_MMW_DEMO_H */
