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

#include "osal_nonos/Event_nonos.h"

ti_nonOS_Event_Handle Event_create(ti_nonOS_Event_Params *__paramsPtr, char *dummy)
{
    ti_nonOS_Event_Object *event_non_os;

    // dynamically allocating memory for the event struct
    event_non_os = (ti_nonOS_Event_Object *)malloc(sizeof(ti_nonOS_Event_Object));

    return ((ti_nonOS_Event_Handle)event_non_os);
}


/*
 *  ======== Event_checkEvents ========
 *  Checks postedEvents for matching event conditions.
 *  Returns matchingEvents if a match and consumes matched events,
 *  else returns 0 and consumes nothing.
 *  Called with ints disabled
 */
unsigned int Event_checkEvents(ti_nonOS_Event_Object *event, unsigned int andMask, unsigned int orMask)
{
    unsigned int matchingEvents;

    matchingEvents = orMask & event->postedEvents;

    if ((andMask & event->postedEvents) == andMask)
    {
        matchingEvents |= andMask;
    }

    if (matchingEvents)
    {
        /* consume ALL the matching events */
        event->postedEvents &= ~matchingEvents;
    }

    return (matchingEvents);
}

void Event_post(ti_nonOS_Event_Handle eventHandle, unsigned int eventId)
{
    ti_nonOS_Event_Object *event_non_os = (ti_nonOS_Event_Object *)eventHandle;

    /* or in this eventId */
    event_non_os->postedEvents |= eventId;

    /* check for match, consume matching eventIds if so. */
    // Event_checkEvents(eventHandle, event_non_os->andMask, event_non_os->orMask);
}


unsigned int Event_pend(ti_nonOS_Event_Handle eventHandle, unsigned int andMask, unsigned int orMask, unsigned int timeout)
{
    ti_nonOS_Event_Object *event_non_os = (ti_nonOS_Event_Object *)eventHandle;
    unsigned int           matchingEvents;

    event_non_os->andMask = andMask;
    event_non_os->orMask  = orMask;

    /* check if events are already available */
    matchingEvents = Event_checkEvents(eventHandle, andMask, orMask);

    if (matchingEvents != 0)
    {
    }
    else
    {
        while ((matchingEvents == 0) && (timeout == EventP_WAIT_FOREVER))
        {
            /* check if events are already available */
            matchingEvents = Event_checkEvents(eventHandle, andMask, orMask);
        }
    }


    return (matchingEvents); /* return with matching bits */
}
