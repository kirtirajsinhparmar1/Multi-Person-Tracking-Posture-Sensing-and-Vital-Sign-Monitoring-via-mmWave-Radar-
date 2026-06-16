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

/*
 *  ======== SemaphoreP_nortos.c ========
 */

#include <stdio.h>
#include <stdlib.h>
#include <ti/drivers/osal/SemaphoreP.h>


struct sem_config
{
    SemaphoreP_Params     params;
    volatile unsigned int count;
};

/*
 *  ======== SemaphoreP_create ========
 */
SemaphoreP_Handle SemaphoreP_create(unsigned int       count,
                                    SemaphoreP_Params *params)
{
    struct sem_config *sem_non_os;

    // dynamically allocating memory for the semaphore struct
    sem_non_os = (struct sem_config *)malloc(sizeof(struct sem_config));

    if (params == NULL)
    {
        params = &(sem_non_os->params);
        SemaphoreP_Params_init(params);
    }
    else
    {
        (sem_non_os->params).name = params->name;
        (sem_non_os->params).mode = params->mode;
    }

    // check if the semaphore is binary or counting
    if (params->mode == SemaphoreP_Mode_COUNTING)
    {
        sem_non_os->count             = count;
        (sem_non_os->params).maxCount = params->maxCount;
    }
    else
    {
        (sem_non_os->params).maxCount = 1;
        if (count != 0)
        {
            sem_non_os->count = 1;
        }
        else
        {
            sem_non_os->count = 0;
        }
    }

    return ((SemaphoreP_Handle)sem_non_os);
}

/*
 *  ======== SemaphoreP_delete ========
 */
SemaphoreP_Status SemaphoreP_delete(SemaphoreP_Handle handle)
{
    struct sem_config *sem_non_os = (struct sem_config *)handle;
    free(sem_non_os);
    return (SemaphoreP_OK);
}

/*
 *  ======== SemaphoreP_Params_init ========
 */
void SemaphoreP_Params_init(SemaphoreP_Params *params)
{
    params->mode     = SemaphoreP_Mode_BINARY;
    params->name     = NULL;
    params->maxCount = 1;
}

/*
 *  ======== SemaphoreP_pend ========
 */
SemaphoreP_Status SemaphoreP_pend(SemaphoreP_Handle handle, uint32_t timeout)
{
    struct sem_config *sem_non_os = (struct sem_config *)handle;

    while ((sem_non_os->count == 0) && (timeout == SemaphoreP_WAIT_FOREVER))
        ;
    if (sem_non_os->count > 0)
    {
        (sem_non_os->count)--;
        return (SemaphoreP_OK);
    }
    else
    {
        return (SemaphoreP_TIMEOUT);
    }
}

/*
 *  ======== SemaphoreP_post ========
 */
SemaphoreP_Status SemaphoreP_post(SemaphoreP_Handle handle)
{
    struct sem_config *sem_non_os = (struct sem_config *)handle;
    if (sem_non_os->count < (sem_non_os->params).maxCount)
    {
        (sem_non_os->count)++;
        return (SemaphoreP_OK);
    }
    else
    {
        return (SemaphoreP_FAILURE);
    }
}

/*
 *  ======== SemaphoreP_postFromClock ========
 */
SemaphoreP_Status SemaphoreP_postFromClock(SemaphoreP_Handle handle)
{
    return (SemaphoreP_post(handle));
}

/*
 *  ======== SemaphoreP_postFromISR ========
 */
SemaphoreP_Status SemaphoreP_postFromISR(SemaphoreP_Handle handle)
{
    return (SemaphoreP_post(handle));
}
