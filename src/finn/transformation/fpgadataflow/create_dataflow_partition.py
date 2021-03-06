# Copyright (c) 2020, Xilinx
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of FINN nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import copy

from onnx import helper

from finn.transformation import Transformation
from finn.util.basic import get_by_name, make_build_dir


class CreateDataflowPartition(Transformation):
    """Split a graph into two graphs; one which contains non-FINN-dataflow nodes
    and a StreamingDataflowPartition node, and another which only contains
    FINN dataflow nodes. The StreamingDataflowPartition has a model attribute
    that indicates the filename for the second graph that only contains
    dataflow nodes. No action is taken if there are no dataflow nodes."""

    def __init__(self):
        super().__init__()

    def apply(self, model):
        # TODO we currently assume that all dataflow nodes are connected to
        # each other, forming a single partition. check the assumption and/or
        # improve this.
        all_nodes = list(model.graph.node)
        df_nodes = filter(
            lambda x: get_by_name(x.attribute, "backend") is not None, all_nodes
        )
        df_nodes = filter(
            lambda x: get_by_name(x.attribute, "backend").s.decode("UTF-8")
            == "fpgadataflow",
            df_nodes,
        )
        df_nodes = list(df_nodes)
        non_df_nodes = filter(lambda x: x not in df_nodes, all_nodes)
        non_df_nodes = list(non_df_nodes)

        if len(df_nodes) == 0:
            # no changes if no dataflow nodes are present
            return (model, False)
        else:
            # partition the model into two models
            df_model = copy.deepcopy(model)
            non_df_model = model
            # remove all non-dataflow nodes from the dataflow model
            for node_to_remove in non_df_nodes:
                df_model.graph.node.remove(node_to_remove)
            # identify the entry and exit points for the dataflow part
            df_in = df_model.graph.node[0].input[0]
            df_out = df_model.graph.node[-1].output[0]
            df_in_vi = df_model.get_tensor_valueinfo(df_in)
            df_out_vi = df_model.get_tensor_valueinfo(df_out)
            # set df graph in/out to be df_in/df_out
            df_model.graph.input.remove(df_model.graph.input[0])
            df_model.graph.input.insert(0, df_in_vi)
            df_model.graph.output.remove(df_model.graph.output[0])
            df_model.graph.output.insert(0, df_out_vi)
            df_model_dir = make_build_dir("dataflow_partition_")
            df_model_filename = df_model_dir + "/df_model.onnx"
            df_model.save(df_model_filename)
            # remove all dataflow nodes from the non-dataflow model
            # keep track of where the dataflow part starts
            df_start_ind = all_nodes.index(df_nodes[0])
            for node_to_remove in df_nodes:
                non_df_model.graph.node.remove(node_to_remove)
            # create StreamingDataflow node with df_in/df_out io
            df_node = helper.make_node(
                "StreamingDataflowPartition",
                [df_in],
                [df_out],
                # use the model attribute to mark the df model
                model=df_model_filename,
            )
            non_df_model.graph.node.insert(df_start_ind, df_node)

        return (non_df_model, False)
